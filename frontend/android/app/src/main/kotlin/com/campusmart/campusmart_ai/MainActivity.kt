package com.campusmart.campusmart_ai

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * Hosts the "campusmart.ai/notifications" bridge so the Dart
 * NotificationService can post real Android heads-up notifications for
 * college listings, orders, messages and calls.
 */
class MainActivity : FlutterActivity() {

    private val channelName = "campusmart.ai/notifications"
    private val notificationChannelId = "campusmart_high_importance"

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        createNotificationChannel()
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
            .setMethodCallHandler { call, result ->
                when (call.method) {
                    "requestPermission" -> {
                        requestNotificationPermission()
                        result.success(isPermissionGranted())
                    }
                    "showNotification" -> {
                        val title = call.argument<String>("title") ?: "CampusMart AI"
                        val body = call.argument<String>("body") ?: ""
                        val id = call.argument<Int>("id")
                            ?: (System.currentTimeMillis() and 0x7FFFFFFF).toInt()
                        showNotification(id, title, body)
                        result.success(true)
                    }
                    else -> result.notImplemented()
                }
            }
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
            val manager =
                getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            manager.createNotificationChannel(channel)
        }
    }

    private fun isPermissionGranted(): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            ContextCompat.checkSelfPermission(
                this,
                android.Manifest.permission.POST_NOTIFICATIONS
            ) == PackageManager.PERMISSION_GRANTED
        } else {
            true
        }
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            !isPermissionGranted()
        ) {
            requestPermissions(
                arrayOf(android.Manifest.permission.POST_NOTIFICATIONS),
                9001
            )
        }
    }

    private fun showNotification(id: Int, title: String, body: String) {
        if (!isPermissionGranted()) {
            requestNotificationPermission()
        }
        val builder = NotificationCompat.Builder(this, notificationChannelId)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
        try {
            NotificationManagerCompat.from(this).notify(id, builder.build())
        } catch (_: SecurityException) {
            // Permission revoked mid-session; the in-app bell still works.
        }
    }
}
