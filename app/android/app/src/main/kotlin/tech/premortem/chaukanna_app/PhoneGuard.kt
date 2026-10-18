package tech.premortem.chaukanna_app

import android.Manifest
import android.app.Activity
import android.app.role.RoleManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioDeviceInfo
import android.media.AudioManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.telecom.TelecomManager
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel

/**
 * Bridge between the Flutter app and the phone's real calls: call-state events
 * from [GuardService], permission requests, speakerphone, ending a call and
 * bringing the app over the dialer. Everything the app can legally do to a
 * normal call lives here; Android gives no access to the call audio itself.
 */
object PhoneGuard : EventChannel.StreamHandler {
    const val METHODS = "chaukanna/phone"
    const val EVENTS = "chaukanna/phone/events"
    private const val PREFS = "chaukanna_guard"
    private const val KEY_ENABLED = "enabled"
    private const val REQUEST_CODE = 4107

    private val main = Handler(Looper.getMainLooper())
    private var sink: EventChannel.EventSink? = null
    private var last: Map<String, String>? = null
    private var pendingPermissions: MethodChannel.Result? = null
    private var pendingScreening: MethodChannel.Result? = null
    private const val ROLE_REQUEST = 4108

    // ---- call-state events ----------------------------------------------------

    fun emit(state: String, number: String) {
        val event = mapOf("state" to state, "number" to number)
        last = event
        main.post { sink?.success(event) }
    }

    override fun onListen(arguments: Any?, events: EventChannel.EventSink?) {
        sink = events
        // A call that began before Flutter was listening still gets reported.
        last?.takeIf { it["state"] != "idle" }?.let { events?.success(it) }
    }

    override fun onCancel(arguments: Any?) {
        sink = null
    }

    // ---- method calls ---------------------------------------------------------

    fun handle(activity: Activity, call: MethodCall, result: MethodChannel.Result) {
        val ctx = activity.applicationContext
        when (call.method) {
            "status" -> result.success(status(ctx))
            "requestPermissions" -> requestPermissions(activity, result)
            "openOverlaySettings" -> {
                activity.startActivity(
                    Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:${ctx.packageName}"))
                )
                result.success(null)
            }
            "start" -> result.success(start(ctx))
            "stop" -> {
                setEnabled(ctx, false)
                ctx.stopService(Intent(ctx, GuardService::class.java))
                result.success(true)
            }
            "screeningStatus" -> result.success(screeningHeld(ctx))
            "requestScreening" -> requestScreening(activity, result)
            "screenedLog" -> result.success(BlockLog.read(ctx))
            "endCall" -> result.success(endCall(ctx))
            "setSpeaker" -> result.success(setSpeaker(ctx, call.argument<Boolean>("on") == true))
            "bringToFront" -> result.success(bringToFront(ctx))
            else -> result.notImplemented()
        }
    }

    private fun granted(ctx: Context, permission: String) =
        ContextCompat.checkSelfPermission(ctx, permission) == PackageManager.PERMISSION_GRANTED

    fun isEnabled(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(KEY_ENABLED, false)

    private fun setEnabled(ctx: Context, on: Boolean) =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_ENABLED, on).apply()

    private fun status(ctx: Context): Map<String, Boolean> = mapOf(
        "microphone" to granted(ctx, Manifest.permission.RECORD_AUDIO),
        "phone" to granted(ctx, Manifest.permission.READ_PHONE_STATE),
        "callLog" to granted(ctx, Manifest.permission.READ_CALL_LOG),
        "answerCalls" to granted(ctx, Manifest.permission.ANSWER_PHONE_CALLS),
        "notifications" to (Build.VERSION.SDK_INT < 33 || granted(ctx, Manifest.permission.POST_NOTIFICATIONS)),
        "overlay" to Settings.canDrawOverlays(ctx),
        "enabled" to isEnabled(ctx),
    )

    private fun requestPermissions(activity: Activity, result: MethodChannel.Result) {
        val wanted = mutableListOf(
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.READ_PHONE_STATE,
            Manifest.permission.READ_CALL_LOG,
            Manifest.permission.ANSWER_PHONE_CALLS,
        )
        if (Build.VERSION.SDK_INT >= 33) wanted += Manifest.permission.POST_NOTIFICATIONS
        val missing = wanted.filter { !granted(activity, it) }
        if (missing.isEmpty()) {
            result.success(status(activity.applicationContext))
            return
        }
        pendingPermissions?.success(status(activity.applicationContext))
        pendingPermissions = result
        ActivityCompat.requestPermissions(activity, missing.toTypedArray(), REQUEST_CODE)
    }

    fun onPermissionResult(activity: Activity, requestCode: Int) {
        if (requestCode != REQUEST_CODE) return
        pendingPermissions?.success(status(activity.applicationContext))
        pendingPermissions = null
    }

    /** Whether Chaukanna is the phone's call-screening app (Android 10+), which lets it see numbers before they ring. */
    private fun screeningHeld(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT < 29) return false
        val rm = ctx.getSystemService(Context.ROLE_SERVICE) as RoleManager
        return rm.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING) && rm.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)
    }

    private fun requestScreening(activity: Activity, result: MethodChannel.Result) {
        if (Build.VERSION.SDK_INT < 29) {
            result.success(false)
            return
        }
        val rm = activity.getSystemService(Context.ROLE_SERVICE) as RoleManager
        if (!rm.isRoleAvailable(RoleManager.ROLE_CALL_SCREENING)) {
            result.success(false)
            return
        }
        if (rm.isRoleHeld(RoleManager.ROLE_CALL_SCREENING)) {
            result.success(true)
            return
        }
        pendingScreening?.success(false)
        pendingScreening = result
        @Suppress("DEPRECATION")
        activity.startActivityForResult(rm.createRequestRoleIntent(RoleManager.ROLE_CALL_SCREENING), ROLE_REQUEST)
    }

    fun onActivityResult(activity: Activity, requestCode: Int) {
        if (requestCode != ROLE_REQUEST) return
        pendingScreening?.success(screeningHeld(activity.applicationContext))
        pendingScreening = null
    }

    /** Foreground service of type microphone: Android only allows it to start while the app is visible. */
    private fun start(ctx: Context): Boolean {
        if (!granted(ctx, Manifest.permission.RECORD_AUDIO) || !granted(ctx, Manifest.permission.READ_PHONE_STATE)) {
            return false
        }
        setEnabled(ctx, true)
        ContextCompat.startForegroundService(ctx, Intent(ctx, GuardService::class.java))
        return true
    }

    /** Hang up the real call. Needs the "answer phone calls" permission and Android 9 or newer. */
    private fun endCall(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT < 28 || !granted(ctx, Manifest.permission.ANSWER_PHONE_CALLS)) return false
        return try {
            @Suppress("DEPRECATION")
            (ctx.getSystemService(Context.TELECOM_SERVICE) as TelecomManager).endCall()
        } catch (_: SecurityException) {
            false
        }
    }

    /** Loudspeaker, so the phone's own microphone can hear the caller. */
    private fun setSpeaker(ctx: Context, on: Boolean): Boolean {
        val am = ctx.getSystemService(Context.AUDIO_SERVICE) as AudioManager
        return try {
            if (Build.VERSION.SDK_INT >= 31) {
                if (on) {
                    val speaker = am.availableCommunicationDevices.firstOrNull {
                        it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER
                    }
                    speaker?.let { am.setCommunicationDevice(it) } ?: false
                } else {
                    am.clearCommunicationDevice()
                    true
                }
            } else {
                @Suppress("DEPRECATION")
                am.isSpeakerphoneOn = on
                true
            }
        } catch (_: Exception) {
            false
        }
    }

    /** Put the app in front of the dialer. Android only allows this with "display over other apps". */
    private fun bringToFront(ctx: Context): Boolean {
        if (!Settings.canDrawOverlays(ctx)) return false
        ctx.startActivity(
            Intent(ctx, MainActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_REORDER_TO_FRONT or Intent.FLAG_ACTIVITY_SINGLE_TOP
            )
        )
        return true
    }
}
