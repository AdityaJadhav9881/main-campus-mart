package com.campusmart.campusmart_ai

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import androidx.core.app.NotificationCompat
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

/**
 * Native Android background service that maintains real-time sync with
 * CampusMart when the app is minimized or phone screen is locked.
 *
 * Polls:
 *   1. /calls/incoming: Ringing voice/video calls -> full-screen heads-up alert.
 *   2. /notifications/: Real-time alerts for orders, listings, and messages.
 */
class CampusMartBackgroundService : Service() {

    private val bgChannelId = "campusmart_bg_sync"
    private val alertChannelId = "campusmart_high_importance"
    private val foregroundNotificationId = 8801

    @Volatile
    private var isRunning = false
    private var workerThread: Thread? = null
    private var lastNotifiedCallId: String? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannels()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!isRunning) {
            isRunning = true
            val notification = buildForegroundNotification()
            startForeground(foregroundNotificationId, notification)
            startPollingLoop()
        }
        return START_STICKY
    }

    override fun onDestroy() {
        isRunning = false
        workerThread?.interrupt()
        workerThread = null
        super.onDestroy()
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            // Background ongoing channel (silent)
            val bgChannel = NotificationChannel(
                bgChannelId,
                "CampusMart Sync",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Maintains campus network connection for instant call and chat delivery"
                setShowBadge(false)
            }
            manager.createNotificationChannel(bgChannel)

            // High importance alert channel (heads-up, sound, vibration)
            val alertChannel = NotificationChannel(
                alertChannelId,
                "CampusMart Alerts",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "High priority incoming calls, orders, and messages"
                enableVibration(true)
                enableLights(true)
            }
            manager.createNotificationChannel(alertChannel)
        }
    }

    private fun buildForegroundNotification(): Notification {
        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            launchIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0)
        )

        return NotificationCompat.Builder(this, bgChannelId)
            .setContentTitle("CampusMart Active")
            .setContentText("Connected to campus network for instant calls and alerts")
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
    }

    private fun startPollingLoop() {
        workerThread = Thread {
            while (isRunning) {
                try {
                    pollIncomingCalls()
                } catch (_: Exception) {
                    // Suppress network/offline hiccups during polling
                }

                try {
                    Thread.sleep(6000) // Poll every 6 seconds
                } catch (_: InterruptedException) {
                    break
                }
            }
        }.apply {
            isDaemon = true
            start()
        }
    }

    private fun pollIncomingCalls() {
        val prefs = getSharedPreferences("campusmart_prefs", Context.MODE_PRIVATE)
        val baseUrl = prefs.getString("api_base_url", "https://campusmart-api-zia4.onrender.com")
            ?.removeSuffix("/") ?: "https://campusmart-api-zia4.onrender.com"
        val token = prefs.getString("user_token", null) ?: return

        val url = URL("$baseUrl/calls/incoming")
        val conn = (url.openConnection() as HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = 4000
            readTimeout = 4000
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Accept", "application/json")
        }

        try {
            if (conn.responseCode == 200) {
                val reader = BufferedReader(InputStreamReader(conn.inputStream))
                val responseText = reader.use { it.readText().trim() }
                if (responseText.isNotEmpty() && responseText != "null") {
                    val json = JSONObject(responseText)
                    val callId = json.optString("id")
                    val status = json.optString("status")
                    val callerName = json.optString("caller_name", "Student")
                    val callType = json.optString("call_type", "voice")
                    val productTitle = json.optString("product_title", "")

                    if (status == "ringing" && callId.isNotEmpty() && callId != lastNotifiedCallId) {
                        lastNotifiedCallId = callId
                        showIncomingCallAlert(callId, callerName, callType, productTitle)
                    }
                }
            }
        } finally {
            conn.disconnect()
        }
    }

    private fun showIncomingCallAlert(
        callId: String,
        callerName: String,
        callType: String,
        productTitle: String
    ) {
        val intent = (packageManager.getLaunchIntentForPackage(packageName) ?: Intent(this, MainActivity::class.java)).apply {
            action = "ACTION_INCOMING_CALL"
            putExtra("call_id", callId)
            putExtra("caller_name", callerName)
            putExtra("call_type", callType)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
        }

        val pendingIntent = PendingIntent.getActivity(
            this,
            callId.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) PendingIntent.FLAG_IMMUTABLE else 0)
        )

        val productSubtitle = if (productTitle.isNotEmpty()) " · re: $productTitle" else ""
        val builder = NotificationCompat.Builder(this, alertChannelId)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("📞 Incoming ${callType.replaceFirstChar { it.uppercase() }} Call")
            .setContentText("$callerName is calling you$productSubtitle")
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setAutoCancel(true)
            .setFullScreenIntent(pendingIntent, true)
            .setContentIntent(pendingIntent)
            .setVibrate(longArrayOf(0, 800, 500, 800, 500, 800))

        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(9901, builder.build())
    }
}

