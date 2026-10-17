package com.campusmart.campusmart_ai

import android.app.AlarmManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.Ringtone
import android.media.RingtoneManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

/**
 * Persistent Android Foreground Service for CampusMart AI.
 *
 * Keeps calls and real-time campus notifications functioning reliably even when
 * the Flutter app is minimized, locked, or swiped away from the recent apps list.
 */
class CampusMartBackgroundService : Service() {

    private val serviceJob = SupervisorJob()
    private val serviceScope = CoroutineScope(Dispatchers.IO + serviceJob)

    private var wakeLock: PowerManager.WakeLock? = null
    private var isRunning = false
    private var lastRingingCallId: String? = null
    private var currentRingtone: Ringtone? = null

    companion object {
        const val PERSISTENT_CHANNEL_ID = "campusmart_bg_service"
        const val CALLS_CHANNEL_ID = "campusmart_calls_and_alerts"
        const val PERSISTENT_NOTIFICATION_ID = 1001
        const val CALL_NOTIFICATION_ID = 1002

        fun startService(context: Context) {
            try {
                val intent = Intent(context, CampusMartBackgroundService::class.java)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
            } catch (_: Exception) {}
        }

        fun stopService(context: Context) {
            try {
                val intent = Intent(context, CampusMartBackgroundService::class.java)
                context.stopService(intent)
            } catch (_: Exception) {}
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        try {
            createNotificationChannels()
            acquireWakeLock()
        } catch (_: Exception) {}
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        try {
            val notification = buildPersistentNotification()
            startForeground(PERSISTENT_NOTIFICATION_ID, notification)

            if (!isRunning) {
                isRunning = true
                startPollingLoop()
            }
        } catch (_: Exception) {}

        return START_STICKY
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            // 1. Silent low-importance persistent service channel
            val serviceChannel = NotificationChannel(
                PERSISTENT_CHANNEL_ID,
                "Campus Network Monitor",
                NotificationManager.IMPORTANCE_MIN
            ).apply {
                description = "Keeps campus calls and urgent alerts active in background"
                setShowBadge(false)
            }
            manager.createNotificationChannel(serviceChannel)

            // 2. High-importance heads-up call and alert channel
            val callChannel = NotificationChannel(
                CALLS_CHANNEL_ID,
                "CampusMart Calls & Alerts",
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = "Incoming voice/video calls and instant buyer notifications"
                enableVibration(true)
                enableLights(true)
                setSound(
                    RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE),
                    AudioAttributes.Builder()
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
                        .build()
                )
            }
            manager.createNotificationChannel(callChannel)
        }
    }

    private fun buildPersistentNotification(): Notification {
        val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
        val pendingIntent = PendingIntent.getActivity(
            this,
            0,
            launchIntent,
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )

        return NotificationCompat.Builder(this, PERSISTENT_CHANNEL_ID)
            .setSmallIcon(android.R.drawable.stat_notify_chat)
            .setContentTitle("CampusMart Active")
            .setContentText("Listening for student calls & buyer messages")
            .setContentIntent(pendingIntent)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .build()
    }

    private fun acquireWakeLock() {
        try {
            val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = powerManager.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "CampusMart::BackgroundServiceWakeLock"
            ).apply {
                setReferenceCounted(false)
                acquire(10 * 60 * 1000L) // 10 min safe timeout
            }
        } catch (_: Exception) {}
    }

    private fun startPollingLoop() {
        serviceScope.launch {
            var cycleCount = 0
            while (isActive && isRunning) {
                try {
                    val prefs = getSharedPreferences("campusmart_prefs", Context.MODE_PRIVATE)
                    val apiUrl = prefs.getString("api_base_url", "") ?: ""
                    val token = prefs.getString("user_token", "") ?: ""

                    if (apiUrl.isNotEmpty() && token.isNotEmpty()) {
                        // 1. Fast incoming call poll (every ~3 seconds)
                        checkIncomingCalls(apiUrl, token)

                        // 2. Notification poll (every ~9 seconds / 3 cycles)
                        cycleCount++
                        if (cycleCount >= 3) {
                            cycleCount = 0
                            checkNotifications(apiUrl, token)
                        }
                    }
                } catch (_: Exception) {}

                delay(3000)
            }
        }
    }

    private fun checkIncomingCalls(apiUrl: String, token: String) {
        try {
            val root = apiUrl.trimEnd('/')
            val url = URL("$root/calls/incoming")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                setRequestProperty("Authorization", "Bearer $token")
                setRequestProperty("Accept", "application/json")
                connectTimeout = 4000
                readTimeout = 4000
                doInput = true
            }

            if (conn.responseCode == 200) {
                val responseText = conn.inputStream.bufferedReader().use { it.readText() }.trim()
                if (responseText.isNotEmpty() && responseText != "null") {
                    val json = JSONObject(responseText)
                    val callId = json.optString("id")
                    val callerName = json.optString("caller_name", "Student")
                    val callType = json.optString("call_type", "voice")
                    val productTitle = json.optString("product_title", "")
                    val status = json.optString("status", "")

                    if (status == "ringing" && callId.isNotEmpty()) {
                        if (lastRingingCallId != callId) {
                            lastRingingCallId = callId
                            showIncomingCallAlert(callId, callerName, callType, productTitle)
                        }
                    } else {
                        if (lastRingingCallId != null) {
                            dismissIncomingCallAlert()
                            lastRingingCallId = null
                        }
                    }
                } else {
                    if (lastRingingCallId != null) {
                        dismissIncomingCallAlert()
                        lastRingingCallId = null
                    }
                }
            } else {
                if (lastRingingCallId != null) {
                    dismissIncomingCallAlert()
                    lastRingingCallId = null
                }
            }
            conn.disconnect()
        } catch (_: Exception) {}
    }

    private fun checkNotifications(apiUrl: String, token: String) {
        try {
            val root = apiUrl.trimEnd('/')
            val url = URL("$root/notifications/?mark_pushed=true")
            val conn = (url.openConnection() as HttpURLConnection).apply {
                requestMethod = "GET"
                setRequestProperty("Authorization", "Bearer $token")
                setRequestProperty("Accept", "application/json")
                connectTimeout = 5000
                readTimeout = 5000
                doInput = true
            }

            if (conn.responseCode == 200) {
                val responseText = conn.inputStream.bufferedReader().use { it.readText() }
                val json = JSONObject(responseText)
                val notifications = json.optJSONArray("notifications")
                if (notifications != null) {
                    for (i in 0 until notifications.length()) {
                        val item = notifications.getJSONObject(i)
                        val isRead = item.optBoolean("is_read", false)
                        val isPushed = item.optBoolean("is_pushed", false)
                        val notifType = item.optString("type", "")

                        // Only pop real unpushed, unread notifications (skip incoming_call type as handled above)
                        if (!isRead && !isPushed && notifType != "incoming_call") {
                            val id = (System.currentTimeMillis() and 0x7FFFFFFF).toInt()
                            val title = item.optString("title", "CampusMart Alert")
                            val body = item.optString("body", "")
                            showTrayNotification(id, title, body)
                        }
                    }
                }
            }
            conn.disconnect()
        } catch (_: Exception) {}
    }

    private fun showIncomingCallAlert(callId: String, callerName: String, callType: String, productTitle: String) {
        try {
            val fullScreenIntent = Intent(this, MainActivity::class.java).apply {
                action = Intent.ACTION_MAIN
                addCategory(Intent.CATEGORY_LAUNCHER)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
                putExtra("incoming_call", true)
                putExtra("call_id", callId)
                putExtra("caller_name", callerName)
                putExtra("call_type", callType)
            }

            val fullScreenPendingIntent = PendingIntent.getActivity(
                this,
                callId.hashCode(),
                fullScreenIntent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )

            val subtext = if (productTitle.isNotEmpty()) " · re: $productTitle" else ""
            val contentText = "$callerName is calling you$subtext"

            val notification = NotificationCompat.Builder(this, CALLS_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_chat)
                .setContentTitle("📞 Incoming ${callType.capitalize()} Call")
                .setContentText(contentText)
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setCategory(NotificationCompat.CATEGORY_CALL)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setFullScreenIntent(fullScreenPendingIntent, true)
                .setContentIntent(fullScreenPendingIntent)
                .setAutoCancel(true)
                .setOngoing(true)
                .build()

            NotificationManagerCompat.from(this).notify(CALL_NOTIFICATION_ID, notification)
            startServiceRingtone()
        } catch (_: Exception) {}
    }

    private fun dismissIncomingCallAlert() {
        try {
            NotificationManagerCompat.from(this).cancel(CALL_NOTIFICATION_ID)
            stopServiceRingtone()
        } catch (_: Exception) {}
    }

    private fun showTrayNotification(id: Int, title: String, body: String) {
        try {
            val launchIntent = packageManager.getLaunchIntentForPackage(packageName)
            val pendingIntent = PendingIntent.getActivity(
                this,
                id,
                launchIntent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )

            val builder = NotificationCompat.Builder(this, CALLS_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_chat)
                .setContentTitle(title)
                .setContentText(body)
                .setStyle(NotificationCompat.BigTextStyle().bigText(body))
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setContentIntent(pendingIntent)
                .setAutoCancel(true)

            NotificationManagerCompat.from(this).notify(id, builder.build())
        } catch (_: Exception) {}
    }

    private fun startServiceRingtone() {
        try {
            val ringtoneUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            currentRingtone = RingtoneManager.getRingtone(applicationContext, ringtoneUri)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                currentRingtone?.isLooping = true
            }
            currentRingtone?.play()

            val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vm = getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
                vm?.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator?.vibrate(
                    VibrationEffect.createWaveform(longArrayOf(0, 800, 500, 800, 500), 1)
                )
            } else {
                @Suppress("DEPRECATION")
                vibrator?.vibrate(longArrayOf(0, 800, 500, 800, 500), 1)
            }
        } catch (_: Exception) {}
    }

    private fun stopServiceRingtone() {
        try {
            currentRingtone?.stop()
            currentRingtone = null
            val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val vm = getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as? VibratorManager
                vm?.defaultVibrator
            } else {
                @Suppress("DEPRECATION")
                getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
            }
            vibrator?.cancel()
        } catch (_: Exception) {}
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        try {
            // AlarmManager restart hook so service respawns if app is swiped away
            val restartServiceIntent = Intent(applicationContext, CampusMartBackgroundService::class.java).apply {
                setPackage(packageName)
            }
            val restartServicePendingIntent = PendingIntent.getService(
                applicationContext,
                1,
                restartServiceIntent,
                PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE
            )
            val alarmService = applicationContext.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            alarmService.set(
                AlarmManager.ELAPSED_REALTIME,
                SystemClock.elapsedRealtime() + 1000,
                restartServicePendingIntent
            )
        } catch (_: Exception) {}
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        isRunning = false
        dismissIncomingCallAlert()
        serviceScope.cancel()
        try {
            if (wakeLock?.isHeld == true) {
                wakeLock?.release()
            }
        } catch (_: Exception) {}
        super.onDestroy()
    }
}

