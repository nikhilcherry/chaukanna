package tech.premortem.chaukanna_app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.provider.CallLog
import android.telephony.TelephonyManager

/**
 * Keeps Chaukanna alive while the phone is being used for ordinary calls, and
 * reports each call's state and number to Flutter. The notification is required by
 * Android for anything that holds the microphone in the background.
 */
class GuardService : Service() {
    private var receiver: BroadcastReceiver? = null
    private var lastNumber = ""

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Call protection", NotificationManager.IMPORTANCE_LOW)
            )
        }
        val open = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val builder = if (Build.VERSION.SDK_INT >= 26) Notification.Builder(this, CHANNEL_ID) else Notification.Builder(this)
        val notification = builder
            .setContentTitle("Chaukanna is watching your calls")
            .setContentText("Tap to open. Turn it off in the app.")
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
        register()
    }

    @Suppress("DEPRECATION")
    private fun register() {
        val r = object : BroadcastReceiver() {
            override fun onReceive(context: Context, intent: Intent) {
                val raw = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return
                val incoming = intent.getStringExtra(TelephonyManager.EXTRA_INCOMING_NUMBER).orEmpty()
                if (incoming.isNotEmpty()) lastNumber = incoming
                when (raw) {
                    TelephonyManager.EXTRA_STATE_RINGING -> PhoneGuard.emit("ringing", lastNumber)
                    TelephonyManager.EXTRA_STATE_OFFHOOK -> {
                        if (lastNumber.isEmpty()) lastNumber = latestLoggedNumber()
                        PhoneGuard.emit("offhook", lastNumber)
                    }
                    TelephonyManager.EXTRA_STATE_IDLE -> {
                        PhoneGuard.emit("idle", "")
                        lastNumber = ""
                    }
                }
            }
        }
        registerReceiver(r, IntentFilter(TelephonyManager.ACTION_PHONE_STATE_CHANGED))
        receiver = r
    }

    /** Android 10+ often leaves the number out of the broadcast; the call log has the last one. */
    private fun latestLoggedNumber(): String = try {
        contentResolver.query(
            CallLog.Calls.CONTENT_URI,
            arrayOf(CallLog.Calls.NUMBER),
            null,
            null,
            "${CallLog.Calls.DATE} DESC",
        )?.use { if (it.moveToFirst()) it.getString(0).orEmpty() else "" } ?: ""
    } catch (_: SecurityException) {
        ""
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int) = START_STICKY

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        receiver?.let { unregisterReceiver(it) }
        receiver = null
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL_ID = "chaukanna_guard"
        private const val NOTIFICATION_ID = 4107
    }
}
