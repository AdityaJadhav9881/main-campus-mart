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
import android.net.wifi.WifiManager
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
 * Persistent Android Foreground Service for CampusMart AI (Android 14-16 API 34-36).
 *
 * Keeps calls ringing and real-time campus notifications functioning reliably even when
 * the Flutter app is minimized, screen is locked, or swiped away from the recent apps list.
 */
class CampusMartBackgroundService : Service() {

    private val serviceJob = SupervisorJob()
    private val serviceScope = CoroutineScope(Dispatchers.IO + serviceJob)

    private var wakeLock: PowerManager.WakeLock? = null
    private var wifiLock: WifiManager.WifiLock? = null
    private var isRunning = false
    private var lastRingingCallId: String? = null
    private var currentRingtone: Ringtone? = null

    companion object {
        const val PERSISTENT_CHANNEL_ID = "campusmart_bg_service"
        const val CALLS_CHANNEL_ID = "campusmart_incoming_calls_v2"
        const val PERSISTENT_NOTIFICATION_ID = 1001
        const val CALL_NOTIFICATION_ID = 1002
        const val ACTION_DECLINE_CALL = "com.campusmart.campusmart_ai.ACTION_DECLINE_CALL"

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
            acquireLocks()
        } catch (_: Exception) {}
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_DECLINE_CALL) {
            val callId = intent.getStringExtra("call_id")
            dismissIncomingCallAlert()
            if (!callId.isNullOrEmpty()) {
                declineCallInBackground(callId)
            }
            return START_STICKY
        }

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

    private fun declineCallInBackground(callId: String) {
        serviceScope.launch {
            try {
                val prefs = getSharedPreferences("campusmart_prefs", Context.MODE_PRIVATE)
                val apiUrl = prefs.getString("api_base_url", "") ?: ""
                val token = prefs.getString("user_token", "") ?: ""
                if (apiUrl.isNotEmpty() && token.isNotEmpty()) {
                    val root = apiUrl.trimEnd('/')
                    val url = URL("$root/calls/$callId/decline")
                    val conn = (url.openConnection() as HttpURLConnection).apply {
                        requestMethod = "POST"
                        setRequestProperty("Authorization", "Bearer $token")
                        connectTimeout = 3000
                        readTimeout = 3000
                    }
                    conn.responseCode
                    conn.disconnect()
                }
            } catch (_: Exception) {}
        }
    }

    private fun createNotificationChannels() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

            // 1. Silent persistent monitor channel
            val serviceChannel = NotificationChannel(
                PERSISTENT_CHANNEL_ID,
                "Campus Network Monitor",
                NotificationManager.IMPORTANCE_MIN
            ).apply {
                description = "Keeps campus calls and urgent alerts active in background"
                setShowBadge(false)
            }
            manager.createNotificationChannel(serviceChannel)

            // 2. High-importance heads-up incoming call channel
            val ringtoneUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE)
            val callChannel = NotificationChannel(
                CALLS_CHANNEL_ID,
                "CampusMart Incoming Calls",
                NotificationManager.IMPORTANCE_MAX
            ).apply {
                description = "Real-time incoming student voice and video calls"
                enableVibration(true)
                enableLights(true)
                setBypassDnd(true)
                lockscreenVisibility = Notification.VISIBILITY_PUBLIC
                setSound(
                    ringtoneUri,
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

    private fun acquireLocks() {
        try {
            val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
            wakeLock = powerManager.newWakeLock(
                PowerManager.PARTIAL_WAKE_LOCK,
                "CampusMart::BackgroundWakeLock"
            ).apply {
                setReferenceCounted(false)
                acquire(60 * 60 * 1000L) // 1 hr rolling lock
            }

            val wifiManager = applicationContext.getSystemService(Context.WIFI_SERVICE) as? WifiManager
            wifiLock = wifiManager?.createWifiLock(
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                    WifiManager.WIFI_MODE_FULL_LOW_LATENCY
                } else {
                    @Suppress("DEPRECATION")
                    WifiManager.WIFI_MODE_FULL_HIGH_PERF
                },
                "CampusMart::BackgroundWifiLock"
            )?.apply {
                setReferenceCounted(false)
                acquire()
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
                        // 1. Fast 2-second incoming call poll
                        checkIncomingCalls(apiUrl, token)

                        // 2. Notification poll every ~8 seconds (4 cycles)
                        cycleCount++
                        if (cycleCount >= 4) {
                            cycleCount = 0
                            checkNotifications(apiUrl, token)
                        }
                    }
                } catch (_: Exception) {}

                delay(2000)
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
                            showIncomingCallAlert(json.toString(), callId, callerName, callType, productTitle)
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

    private fun showIncomingCallAlert(
        callJson: String,
        callId: String,
        callerName: String,
        callType: String,
        productTitle: String
    ) {
        try {
            // Full screen intent to open MainActivity
            val fullScreenIntent = Intent(this, MainActivity::class.java).apply {
                action = Intent.ACTION_MAIN
                addCategory(Intent.CATEGORY_LAUNCHER)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
                putExtra("incoming_call_json", callJson)
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

            // Accept action button
            val acceptIntent = Intent(this, MainActivity::class.java).apply {
                action = Intent.ACTION_MAIN
                addCategory(Intent.CATEGORY_LAUNCHER)
                flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP
                putExtra("incoming_call_json", callJson)
                putExtra("auto_answer", true)
                putExtra("call_id", callId)
            }
            val acceptPendingIntent = PendingIntent.getActivity(
                this,
                (callId + "_accept").hashCode(),
                acceptIntent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )

            // Decline action button
            val declineIntent = Intent(this, CampusMartBackgroundService::class.java).apply {
                action = ACTION_DECLINE_CALL
                putExtra("call_id", callId)
            }
            val declinePendingIntent = PendingIntent.getService(
                this,
                (callId + "_decline").hashCode(),
                declineIntent,
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
            )

            val subtext = if (productTitle.isNotEmpty()) " · re: $productTitle" else ""
            val contentText = "$callerName is calling you$subtext"

            val notification = NotificationCompat.Builder(this, CALLS_CHANNEL_ID)
                .setSmallIcon(android.R.drawable.stat_notify_chat)
                .setContentTitle("📞 Incoming ${callType.replaceFirstChar { it.uppercase() }} Call")
                .setContentText(contentText)
                .setPriority(NotificationCompat.PRIORITY_MAX)
                .setCategory(NotificationCompat.CATEGORY_CALL)
                .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
                .setFullScreenIntent(fullScreenPendingIntent, true)
                .setContentIntent(fullScreenPendingIntent)
                .setAutoCancel(false)
                .setOngoing(true)
                .addAction(android.R.drawable.ic_menu_call, "Accept", acceptPendingIntent)
                .addAction(android.R.drawable.ic_menu_close_clear_cancel, "Decline", declinePendingIntent)
                .build()

            NotificationManagerCompat.from(this).notify(CALL_NOTIFICATION_ID, notification)
            startServiceRingtone()

            // Pop up over lockscreen/home if permission allows
            try {
                startActivity(fullScreenIntent)
            } catch (_: Exception) {}
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
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                alarmService.setExactAndAllowWhileIdle(
                    AlarmManager.ELAPSED_REALTIME_WAKEUP,
                    SystemClock.elapsedRealtime() + 1000,
                    restartServicePendingIntent
                )
            } else {
                alarmService.setExact(
                    AlarmManager.ELAPSED_REALTIME_WAKEUP,
                    SystemClock.elapsedRealtime() + 1000,
                    restartServicePendingIntent
                )
            }
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
            if (wifiLock?.isHeld == true) {
                wifiLock?.release()
            }
        } catch (_: Exception) {}
        super.onDestroy()
    }
}
