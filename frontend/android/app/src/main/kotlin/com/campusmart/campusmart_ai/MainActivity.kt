package com.campusmart.campusmart_ai

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Build
import android.os.Bundle
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * Hosts native bridges for:
 *   1. "campusmart.ai/notifications": heads-up alerts & permission handling.
 *   2. "campusmart.ai/native": permission sweeps, incoming call ringtone playback,
 *      and background service credentials management.
 */
class MainActivity : FlutterActivity() {

    private val channelName = "campusmart.ai/notifications"
    private val nativeChannelName = "campusmart.ai/native"
    private val notificationChannelId = "campusmart_high_importance"

    private var currentRingtone: Ringtone? = null
    private var isRinging = false

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        try {
            createNotificationChannel()
        } catch (_: Exception) {}
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        val handler: (io.flutter.plugin.common.MethodCall, MethodChannel.Result) -> Unit = { call, result ->
            when (call.method) {
                "requestPermission" -> {
                    requestNotificationPermission()
                    result.success(isNotificationPermissionGranted())
                }
                "requestAllAppPermissions" -> {
                    requestAllPermissions()
                    result.success(true)
                }
                "showNotification" -> {
                    val title = call.argument<String>("title") ?: "CampusMart AI"
                    val body = call.argument<String>("body") ?: ""
                    val id = call.argument<Int>("id")
                        ?: (System.currentTimeMillis() and 0x7FFFFFFF).toInt()
                    showNotification(id, title, body)
                    result.success(true)
                }
                "startRingtone" -> {
                    startRinging()
                    result.success(true)
                }
                "stopRingtone" -> {
                    stopRinging()
                    result.success(true)
                }
                "saveNativeCredentials" -> {
                    try {
                        val apiUrl = call.argument<String>("apiUrl") ?: ""
                        val token = call.argument<String>("token") ?: ""
                        val userId = call.argument<String>("userId") ?: ""
                        val prefs = getSharedPreferences("campusmart_prefs", Context.MODE_PRIVATE)
                        prefs.edit()
                            .putString("api_base_url", apiUrl)
                            .putString("user_token", token)
                            .putString("user_id", userId)
                            .apply()
                    } catch (_: Exception) {}
                    result.success(true)
                }
                "stopBackgroundService" -> {
                    result.success(true)
                }
                else -> result.notImplemented()
            }
        }

        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler(handler)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, nativeChannelName)
            .setMethodCallHandler(handler)
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                notificationChannelId,
                "CampusMart Alerts",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Listings, orders, messages and calls from your campus network"
                enableVibration(true)
                enableLights(true)
            }
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
    }

    private fun isNotificationPermissionGranted(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ContextCompat.checkSelfPermission(
                this,
                Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
        } else {
            true
        }
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !isNotificationPermissionGranted()) {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(Manifest.permission.POST_NOTIFICATIONS),
                9001
            )
        }
    }

    private fun requestAllPermissions() {
        try {
            val permissionsToRequest = mutableListOf<String>()

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                    permissionsToRequest.add(Manifest.permission.POST_NOTIFICATIONS)
                }
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_MEDIA_IMAGES) != PackageManager.PERMISSION_GRANTED) {
                    permissionsToRequest.add(Manifest.permission.READ_MEDIA_IMAGES)
                }
            } else {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.READ_EXTERNAL_STORAGE) != PackageManager.PERMISSION_GRANTED) {
                    permissionsToRequest.add(Manifest.permission.READ_EXTERNAL_STORAGE)
                }
            }

            if (ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                permissionsToRequest.add(Manifest.permission.CAMERA)
            }
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                permissionsToRequest.add(Manifest.permission.RECORD_AUDIO)
            }

            if (permissionsToRequest.isNotEmpty()) {
                ActivityCompat.requestPermissions(
                    this,
                    permissionsToRequest.toTypedArray(),
                    9002
                )
            }
        } catch (_: Exception) {}
    }

    private fun startRinging() {
        if (isRinging) return
        isRinging = true
        try {
            val ringtoneUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            currentRingtone = RingtoneManager.getRingtone(applicationContext, ringtoneUri)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                currentRingtone?.isLooping = true
            }
            currentRingtone?.play()

            // Vibrate
            val vibrator = getVibrator()
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator?.vibrate(
                    VibrationEffect.createWaveform(
                        longArrayOf(0, 800, 500, 800, 500),
                        1
                    )
                )
            } else {
                @Suppress("DEPRECATION")
                vibrator?.vibrate(longArrayOf(0, 800, 500, 800, 500), 1)
            }
        } catch (_: Exception) {}
    }

    private fun stopRinging() {
        isRinging = false
        try {
            currentRingtone?.stop()
            currentRingtone = null
            getVibrator()?.cancel()
        } catch (_: Exception) {}
    }

    private fun getVibrator(): Vibrator? {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val vibratorManager = getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
            vibratorManager?.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }
    }

    private fun showNotification(id: Int, title: String, body: String) {
        try {
            if (!isNotificationPermissionGranted()) {
                requestNotificationPermission()
            }
            val builder = NotificationCompat.Builder(this, notificationChannelId)
                .setSmallIcon(android.R.drawable.stat_notify_chat)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setAutoCancel(true)
            NotificationManagerCompat.from(this).notify(id, builder.build())
        } catch (_: Exception) {}
    }

    override fun onDestroy() {
        stopRinging()
        super.onDestroy()
    }
}
