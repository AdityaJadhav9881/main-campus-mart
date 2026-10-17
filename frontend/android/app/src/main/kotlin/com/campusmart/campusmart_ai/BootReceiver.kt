package com.campusmart.campusmart_ai

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat

/**
 * Automatically restarts CampusMartBackgroundService after device reboot or app update.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED ||
            intent.action == Intent.ACTION_MY_PACKAGE_REPLACED
        ) {
            val prefs = context.getSharedPreferences("campusmart_prefs", Context.MODE_PRIVATE)
            val token = prefs.getString("user_token", null)
            if (!token.isNullOrEmpty()) {
                val serviceIntent = Intent(context, CampusMartBackgroundService::class.java)
                try {
                    ContextCompat.startForegroundService(context, serviceIntent)
                } catch (_: Exception) {
                    // Suppress startForegroundService restrictions on Android 12+ if in background
                }
            }
        }
    }
}

