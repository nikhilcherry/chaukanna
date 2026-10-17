package tech.premortem.chaukanna_app

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Bundle
import android.provider.Telephony
import android.view.WindowManager
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private var smsReceiver: BroadcastReceiver? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // A call guardian must stay visible: never let the screen time out
        // and lock in the middle of a call (or a stage demo).
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        val messenger = flutterEngine.dartExecutor.binaryMessenger
        MethodChannel(messenger, PhoneGuard.METHODS).setMethodCallHandler { call, result ->
            PhoneGuard.handle(this, call, result)
        }
        EventChannel(messenger, PhoneGuard.EVENTS).setStreamHandler(PhoneGuard)

        // Incoming SMS -> Dart (lib/services/otp_sms.dart), which works out what an OTP is for and sends
        // only that to the guardian. The code itself never leaves the phone.
        EventChannel(messenger, "chaukanna/sms").setStreamHandler(
            object : EventChannel.StreamHandler {
                override fun onListen(arguments: Any?, sink: EventChannel.EventSink) {
                    if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.RECEIVE_SMS)
                        != PackageManager.PERMISSION_GRANTED
                    ) {
                        ActivityCompat.requestPermissions(this@MainActivity, arrayOf(Manifest.permission.RECEIVE_SMS), 42)
                    }
                    val receiver = object : BroadcastReceiver() {
                        override fun onReceive(context: Context, intent: Intent) {
                            val parts = Telephony.Sms.Intents.getMessagesFromIntent(intent) ?: return
                            // A long SMS arrives in several parts: join them per sender.
                            parts.groupBy { it.displayOriginatingAddress ?: "" }.forEach { (from, msgs) ->
                                sink.success(mapOf("sender" to from, "body" to msgs.joinToString("") { it.displayMessageBody ?: "" }))
                            }
                        }
                    }
                    ContextCompat.registerReceiver(
                        this@MainActivity, receiver, IntentFilter(Telephony.Sms.Intents.SMS_RECEIVED_ACTION),
                        ContextCompat.RECEIVER_EXPORTED,
                    )
                    smsReceiver = receiver
                }

                override fun onCancel(arguments: Any?) {
                    smsReceiver?.let { unregisterReceiver(it) }
                    smsReceiver = null
                }
            },
        )
    }

    @Deprecated("Flutter's activity still routes role requests through this")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        @Suppress("DEPRECATION")
        super.onActivityResult(requestCode, resultCode, data)
        PhoneGuard.onActivityResult(this, requestCode)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        PhoneGuard.onPermissionResult(this, requestCode)
    }

    override fun onDestroy() {
        smsReceiver?.let { unregisterReceiver(it) }
        smsReceiver = null
        super.onDestroy()
    }
}
