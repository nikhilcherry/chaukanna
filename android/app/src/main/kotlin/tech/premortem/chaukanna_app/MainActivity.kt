package tech.premortem.chaukanna_app

import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.EventChannel
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
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
}
