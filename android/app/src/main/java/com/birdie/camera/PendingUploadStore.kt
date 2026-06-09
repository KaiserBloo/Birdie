package com.birdie.camera

import android.content.Context
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.util.UUID

data class PendingUpload(
    val imageFile: File?,
    val videoFile: File?,
    val metadataFile: File,
    val capturedAt: String,
    val motionScore: Float,
    val visitId: String?,
    val candidateIndex: Int?,
    val commandId: String?,
    val kind: String,
)

class PendingUploadStore(context: Context) {
    private val directory = File(context.filesDir, "pending_uploads").apply { mkdirs() }

    fun createImage(
        imageFile: File,
        capturedAt: Instant,
        motionScore: Float,
        visitId: String? = null,
        candidateIndex: Int? = null,
    ): PendingUpload {
        val id = UUID.randomUUID().toString()
        val targetImage = File(directory, "$id.jpg")
        val metadata = File(directory, "$id.json")
        imageFile.copyTo(targetImage, overwrite = true)
        val json = JSONObject()
            .put("kind", KIND_CANDIDATE)
            .put("media_name", targetImage.name)
            .put("captured_at", capturedAt.toString())
            .put("motion_score", motionScore.toDouble())
        visitId?.let { json.put("visit_id", it) }
        candidateIndex?.let { json.put("candidate_index", it) }
        metadata.writeText(json.toString())
        return PendingUpload(
            imageFile = targetImage,
            videoFile = null,
            metadataFile = metadata,
            capturedAt = capturedAt.toString(),
            motionScore = motionScore,
            visitId = visitId,
            candidateIndex = candidateIndex,
            commandId = null,
            kind = KIND_CANDIDATE,
        )
    }

    fun createCommandSnapshot(
        imageFile: File,
        capturedAt: Instant,
        motionScore: Float,
        commandId: String,
    ): PendingUpload {
        val id = UUID.randomUUID().toString()
        val targetImage = File(directory, "$id.jpg")
        val metadata = File(directory, "$id.json")
        imageFile.copyTo(targetImage, overwrite = true)
        val json = JSONObject()
            .put("kind", KIND_COMMAND_SNAPSHOT)
            .put("media_name", targetImage.name)
            .put("captured_at", capturedAt.toString())
            .put("motion_score", motionScore.toDouble())
            .put("command_id", commandId)
        metadata.writeText(json.toString())
        return PendingUpload(
            imageFile = targetImage,
            videoFile = null,
            metadataFile = metadata,
            capturedAt = capturedAt.toString(),
            motionScore = motionScore,
            visitId = null,
            candidateIndex = null,
            commandId = commandId,
            kind = KIND_COMMAND_SNAPSHOT,
        )
    }

    fun createVideo(
        videoFile: File,
        capturedAt: Instant,
        motionScore: Float,
        visitId: String,
    ): PendingUpload {
        val id = UUID.randomUUID().toString()
        val targetVideo = File(directory, "$id.mp4")
        val metadata = File(directory, "$id.json")
        videoFile.copyTo(targetVideo, overwrite = true)
        val json = JSONObject()
            .put("kind", KIND_VISIT_VIDEO)
            .put("media_name", targetVideo.name)
            .put("captured_at", capturedAt.toString())
            .put("motion_score", motionScore.toDouble())
            .put("visit_id", visitId)
        metadata.writeText(json.toString())
        return PendingUpload(
            imageFile = null,
            videoFile = targetVideo,
            metadataFile = metadata,
            capturedAt = capturedAt.toString(),
            motionScore = motionScore,
            visitId = visitId,
            candidateIndex = null,
            commandId = null,
            kind = KIND_VISIT_VIDEO,
        )
    }

    fun list(): List<PendingUpload> {
        return directory.listFiles { file -> file.extension == "json" }
            ?.mapNotNull { metadata ->
                val json = JSONObject(metadata.readText())
                val kind = json.optString("kind", KIND_CANDIDATE).ifBlank { KIND_CANDIDATE }
                val defaultExtension = if (kind == KIND_VISIT_VIDEO) ".mp4" else ".jpg"
                val mediaName = json.optString("media_name")
                    .ifBlank { metadata.nameWithoutExtension + defaultExtension }
                val mediaFile = File(directory, mediaName)
                if (!mediaFile.exists()) return@mapNotNull null
                PendingUpload(
                    imageFile = mediaFile.takeIf { kind != KIND_VISIT_VIDEO },
                    videoFile = mediaFile.takeIf { kind == KIND_VISIT_VIDEO },
                    metadataFile = metadata,
                    capturedAt = json.optString("captured_at"),
                    motionScore = json.optDouble("motion_score", 0.0).toFloat(),
                    visitId = json.optString("visit_id").takeIf { it.isNotBlank() },
                    candidateIndex = if (json.has("candidate_index")) {
                        json.optInt("candidate_index")
                    } else {
                        null
                    },
                    commandId = json.optString("command_id").takeIf { it.isNotBlank() },
                    kind = kind,
                )
            }
            .orEmpty()
            .sortedBy { it.capturedAt }
    }

    fun markUploaded(upload: PendingUpload) {
        upload.imageFile?.delete()
        upload.videoFile?.delete()
        upload.metadataFile.delete()
    }

    companion object {
        const val KIND_CANDIDATE = "candidate"
        const val KIND_VISIT_VIDEO = "visit_video"
        const val KIND_COMMAND_SNAPSHOT = "command_snapshot"
    }
}
