package com.birdie.camera

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.BatteryManager
import android.os.Build
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.net.URLEncoder
import java.nio.charset.StandardCharsets
import java.util.concurrent.TimeUnit

data class RemoteCommand(
    val id: String,
    val command: String,
    val payload: JSONObject,
)

class BirdieApiClient(private val context: Context) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .writeTimeout(90, TimeUnit.SECONDS)
        .build()

    fun postStatus(
        backendUrl: String,
        deviceToken: String?,
        deviceId: String,
    ): JSONObject {
        val batteryInfo = batteryInfo()
        val body = JSONObject()
            .put("device_id", deviceId)
            .put("name", "Window feeder phone")
            .put("phone_model", phoneModel())
            .put("battery_level", batteryInfo.level)
            .put("battery_status", batteryInfo.status)
            .put("is_charging", batteryInfo.isCharging)
            .put("power_source", batteryInfo.powerSource)
            .put("temperature_c", batteryInfo.temperatureC)
            .put("network_state", networkState())
            .put("app_version", BuildConfig.VERSION_NAME)
            .toString()
            .toRequestBody("application/json".toMediaType())

        val request = Request.Builder()
            .url(endpoint(backendUrl, "/device/status"))
            .post(body)
            .applyToken(deviceToken)
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Status failed: HTTP ${response.code}")
            return JSONObject(response.body.string())
        }
    }

    fun upload(
        backendUrl: String,
        deviceToken: String?,
        deviceId: String,
        roi: Roi,
        pendingUpload: PendingUpload,
    ): JSONObject {
        val builder = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("device_id", deviceId)
            .addFormDataPart("device_name", "Window feeder phone")
            .addFormDataPart("phone_model", phoneModel())
            .addFormDataPart("motion_score", pendingUpload.motionScore.toString())
            .addFormDataPart("captured_at", pendingUpload.capturedAt)
            .addFormDataPart("network_state", networkState())
            .addFormDataPart("app_version", BuildConfig.VERSION_NAME)
            .addFormDataPart("roi_x", roi.x.toString())
            .addFormDataPart("roi_y", roi.y.toString())
            .addFormDataPart("roi_width", roi.width.toString())
            .addFormDataPart("roi_height", roi.height.toString())
            .addFormDataPart("upload_kind", pendingUpload.kind)
        pendingUpload.imageFile?.let { imageFile ->
            val imageBody = imageFile.asRequestBody("image/jpeg".toMediaType())
            builder.addFormDataPart("image", imageFile.name, imageBody)
        }
        pendingUpload.videoFile?.let { videoFile ->
            val videoBody = videoFile.asRequestBody("video/mp4".toMediaType())
            builder.addFormDataPart("video", videoFile.name, videoBody)
        }
        if (pendingUpload.imageFile == null && pendingUpload.videoFile == null) {
            error("Upload has no media file")
        }
        pendingUpload.visitId?.let { builder.addFormDataPart("visit_id", it) }
        pendingUpload.candidateIndex?.let {
            builder.addFormDataPart("candidate_index", it.toString())
        }
        pendingUpload.commandId?.let { builder.addFormDataPart("command_id", it) }
        val batteryInfo = batteryInfo()
        batteryInfo.level?.let { builder.addFormDataPart("battery_level", it.toString()) }
        batteryInfo.temperatureC?.let { builder.addFormDataPart("temperature_c", it.toString()) }
        val multipart = builder.build()

        val request = Request.Builder()
            .url(endpoint(backendUrl, "/events/upload"))
            .post(multipart)
            .applyToken(deviceToken)
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Upload failed: HTTP ${response.code} ${response.body.string()}")
            return JSONObject(response.body.string())
        }
    }

    fun nextCommand(
        backendUrl: String,
        deviceToken: String?,
        deviceId: String,
    ): RemoteCommand? {
        val encodedDeviceId = URLEncoder.encode(deviceId, StandardCharsets.UTF_8.name())
        val request = Request.Builder()
            .url(endpoint(backendUrl, "/device/commands/next") + "?device_id=$encodedDeviceId")
            .get()
            .applyToken(deviceToken)
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Command poll failed: HTTP ${response.code}")
            val body = response.body.string()
            if (body.isBlank() || body == "null") return null
            val json = JSONObject(body)
            return RemoteCommand(
                id = json.getString("id"),
                command = json.getString("command"),
                payload = json.optJSONObject("payload") ?: JSONObject(),
            )
        }
    }

    fun completeCommand(
        backendUrl: String,
        deviceToken: String?,
        commandId: String,
        status: String,
        errorMessage: String? = null,
    ) {
        val body = JSONObject()
            .put("status", status)
            .put("error_message", errorMessage)
            .toString()
            .toRequestBody("application/json".toMediaType())

        val request = Request.Builder()
            .url(endpoint(backendUrl, "/device/commands/$commandId/complete"))
            .post(body)
            .applyToken(deviceToken)
            .build()

        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) error("Command completion failed: HTTP ${response.code}")
        }
    }

    private fun Request.Builder.applyToken(deviceToken: String?): Request.Builder {
        if (!deviceToken.isNullOrBlank()) {
            addHeader("X-Birdie-Token", deviceToken)
        }
        return this
    }

    private fun endpoint(baseUrl: String, path: String): String {
        return baseUrl.trimEnd('/') + path
    }

    private fun phoneModel(): String {
        return "${Build.MANUFACTURER} ${Build.MODEL}".trim()
    }

    private fun batteryInfo(): BatteryInfo {
        val batteryManager = context.getSystemService(BatteryManager::class.java)
        val levelValue = batteryManager?.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        val intent = context.registerReceiver(null, android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED))
        val statusValue = intent?.getIntExtra(BatteryManager.EXTRA_STATUS, Int.MIN_VALUE)
        val pluggedValue = intent?.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) ?: 0
        val tenths = intent?.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
            ?: Int.MIN_VALUE
        val isCharging = when (statusValue) {
            BatteryManager.BATTERY_STATUS_CHARGING,
            BatteryManager.BATTERY_STATUS_FULL -> true
            BatteryManager.BATTERY_STATUS_DISCHARGING,
            BatteryManager.BATTERY_STATUS_NOT_CHARGING -> false
            else -> null
        }
        return BatteryInfo(
            level = levelValue?.takeIf { it >= 0 }?.toFloat(),
            temperatureC = tenths.takeIf { it != Int.MIN_VALUE }?.let { it / 10f },
            status = batteryStatusLabel(statusValue),
            isCharging = isCharging,
            powerSource = powerSourceLabel(pluggedValue),
        )
    }

    private fun batteryStatusLabel(status: Int?): String? {
        return when (status) {
            BatteryManager.BATTERY_STATUS_CHARGING -> "charging"
            BatteryManager.BATTERY_STATUS_DISCHARGING -> "discharging"
            BatteryManager.BATTERY_STATUS_FULL -> "full"
            BatteryManager.BATTERY_STATUS_NOT_CHARGING -> "not charging"
            BatteryManager.BATTERY_STATUS_UNKNOWN -> "unknown"
            else -> null
        }
    }

    private fun powerSourceLabel(plugged: Int): String {
        return when {
            plugged and BatteryManager.BATTERY_PLUGGED_USB != 0 -> "usb"
            plugged and BatteryManager.BATTERY_PLUGGED_AC != 0 -> "ac"
            plugged and BatteryManager.BATTERY_PLUGGED_WIRELESS != 0 -> "wireless"
            else -> "battery"
        }
    }

    private fun networkState(): String {
        val connectivityManager = context.getSystemService(ConnectivityManager::class.java)
        val network = connectivityManager?.activeNetwork ?: return "offline"
        val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return "unknown"
        return when {
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "cellular"
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
            else -> "unknown"
        }
    }
}

private data class BatteryInfo(
    val level: Float?,
    val temperatureC: Float?,
    val status: String?,
    val isCharging: Boolean?,
    val powerSource: String,
)
