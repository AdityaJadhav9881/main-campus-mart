package com.campusmart.campusmart_ai

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioDeviceInfo
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.Ringtone
import android.media.RingtoneManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.view.WindowManager
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

/**
 * Hosts native bridges for:
 *   1. "campusmart.ai/notifications": heads-up alerts, Android 12-16 call audio routing, and incoming call launch.
 *   2. "campusmart.ai/native": permission sweeps, incoming call ringtone, and background service lifecycle.
 */
class MainActivity : FlutterActivity() {

    private val channelName = "campusmart.ai/notifications"
    private val nativeChannelName = "campusmart.ai/native"
    private val notificationChannelId = "campusmart_high_importance"

    private var currentRingtone: Ringtone? = null
    private var isRinging = false
    private var latestIncomingCallJson: String? = null
    private var notifChannel: MethodChannel? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
                setShowWhenLocked(true)
                setTurnScreenOn(true)
            } else {
                @Suppress("DEPRECATION")
                window.addFlags(
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                )
            }
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
            createNotificationChannel()
            handleIncomingCallIntent(intent)
        } catch (_: Exception) {}
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleIncomingCallIntent(intent)
    }

    private fun handleIncomingCallIntent(intent: Intent?) {
        val callJson = intent?.getStringExtra("incoming_call_json")
        if (!callJson.isNullOrEmpty()) {
            latestIncomingCallJson = callJson
            notifChannel?.invokeMethod("onIncomingCallLaunched", callJson)
        }
    }

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)

        val channel = MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName)
        notifChannel = channel

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
                "configureCallAudio" -> {
                    val enableSpeaker = call.argument<Boolean>("enableSpeaker") ?: true
                    configureCallAudio(enableSpeaker)
                    result.success(true)
                }
                "releaseCallAudio" -> {
                    releaseCallAudio()
                    result.success(true)
                }
                "getInitialIncomingCall" -> {
                    result.success(latestIncomingCallJson)
                }
                "clearInitialIncomingCall" -> {
                    latestIncomingCallJson = null
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
                        if (apiUrl.isNotEmpty() && token.isNotEmpty()) {
                            CampusMartBackgroundService.startService(applicationContext)
                        }
                    } catch (_: Exception) {}
                    result.success(true)
                }
                "stopBackgroundService" -> {
                    try {
                        CampusMartBackgroundService.stopService(applicationContext)
                    } catch (_: Exception) {}
                    result.success(true)
                }
                "shareText" -> {
                    val text = call.argument<String>("text") ?: ""
                    val title = call.argument<String>("title") ?: "Share via"
                    shareText(text, title)
                    result.success(true)
                }
                else -> result.notImplemented()
            }
        }

        channel.setMethodCallHandler(handler)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, nativeChannelName)
            .setMethodCallHandler(handler)
    }

    private fun configureCallAudio(enableSpeaker: Boolean) {
        try {
            val audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                val focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                    .setAudioAttributes(
                        AudioAttributes.Builder()
                            .setUsage(AudioAttributes.USAGE_VOICE_COMMUNICATION)
                            .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                            .build()
                    )
                    .setAcceptsDelayedFocusGain(false)
                    .build()
                audioManager.requestAudioFocus(focusRequest)
            } else {
                @Suppress("DEPRECATION")
                audioManager.requestAudioFocus(
                    null,
                    AudioManager.STREAM_VOICE_CALL,
                    AudioManager.AUDIOFOCUS_GAIN_TRANSIENT
                )
            }

            audioManager.mode = AudioManager.MODE_IN_COMMUNICATION
            audioManager.isMicrophoneMute = false
            val maxVol = audioManager.getStreamMaxVolume(AudioManager.STREAM_VOICE_CALL)
            audioManager.setStreamVolume(
                AudioManager.STREAM_VOICE_CALL,
                (maxVol * 0.85).toInt().coerceAtLeast(1),
                0
            )

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val devices = audioManager.availableCommunicationDevices
                val targetType = if (enableSpeaker) AudioDeviceInfo.TYPE_BUILTIN_SPEAKER else AudioDeviceInfo.TYPE_BUILTIN_EARPIECE
                val targetDevice = devices.find { it.type == targetType }
                    ?: if (enableSpeaker) devices.find { it.type == AudioDeviceInfo.TYPE_BUILTIN_SPEAKER } else null
                if (targetDevice != null) {
                    audioManager.setCommunicationDevice(targetDevice)
                }
            }
            @Suppress("DEPRECATION")
            audioManager.isSpeakerphoneOn = enableSpeaker
        } catch (_: Exception) {}
    }

    private fun releaseCallAudio() {
        try {
            val audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                audioManager.clearCommunicationDevice()
            }
            @Suppress("DEPRECATION")
            audioManager.isSpeakerphoneOn = false
            audioManager.mode = AudioManager.MODE_NORMAL
            @Suppress("DEPRECATION")
            audioManager.abandonAudioFocus(null)
        } catch (_: Exception) {}
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

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                if (ContextCompat.checkSelfPermission(this, Manifest.permission.BLUETOOTH_CONNECT) != PackageManager.PERMISSION_GRANTED) {
                    permissionsToRequest.add(Manifest.permission.BLUETOOTH_CONNECT)
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

            // Exemption from Android battery freezing (prevents OS from freezing background polling/socket)
            val powerManager = getSystemService(Context.POWER_SERVICE) as? PowerManager
            if (powerManager != null && !powerManager.isIgnoringBatteryOptimizations(packageName)) {
                try {
                    val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                        data = Uri.parse("package:$packageName")
                    }
                    startActivity(intent)
                } catch (_: Exception) {}
            }

            // Android 14-16 full-screen intent authorization check
            if (Build.VERSION.SDK_INT >= 34) {
                val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager
                if (notificationManager != null && !notificationManager.canUseFullScreenIntent()) {
                    try {
                        val intent = Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT).apply {
                            data = Uri.parse("package:$packageName")
                        }
                        startActivity(intent)
                    } catch (_: Exception) {}
                }
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

    private fun shareText(text: String, title: String) {
        try {
            val sendIntent = Intent().apply {
                action = Intent.ACTION_SEND
                putExtra(Intent.EXTRA_TEXT, text)
                type = "text/plain"
            }
            val shareIntent = Intent.createChooser(sendIntent, title).apply {
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            startActivity(shareIntent)
        } catch (_: Exception) {}
    }

    override fun onDestroy() {
        stopRinging()
        super.onDestroy()
    }
}
