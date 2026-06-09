package com.birdie.camera

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.activity.ComponentActivity
import androidx.activity.result.contract.ActivityResultContracts
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.Preview
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.camera.video.FileOutputOptions
import androidx.camera.video.Quality
import androidx.camera.video.QualitySelector
import androidx.camera.video.Recorder
import androidx.camera.video.Recording
import androidx.camera.video.VideoCapture
import androidx.camera.video.VideoRecordEvent
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.time.Instant
import java.util.UUID
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

private enum class VisitState(val label: String) {
    IDLE("idle"),
    ACTIVE("active"),
    SETTLING("settling"),
}

class MainActivity : ComponentActivity() {
    private lateinit var previewView: PreviewView
    private lateinit var roiOverlay: RoiOverlayView
    private lateinit var statusText: TextView
    private lateinit var debugStatsText: TextView
    private lateinit var backendUrlInput: EditText
    private lateinit var deviceTokenInput: EditText
    private lateinit var statusButton: Button
    private lateinit var retryButton: Button

    private lateinit var cameraExecutor: ExecutorService
    private lateinit var pendingUploadStore: PendingUploadStore
    private lateinit var apiClient: BirdieApiClient
    private var remoteLoopJob: Job? = null

    private val roi = Roi.Default
    private var imageCapture: ImageCapture? = null
    private var videoCapture: VideoCapture<Recorder>? = null
    private var captureInProgress = false
    private var capturesStarted = 0
    private var uploadsSucceeded = 0
    private var uploadsQueued = 0
    private var videoRecording = false
    private var activeRecording: Recording? = null
    private var activeVideoFile: File? = null
    private var activeVideoVisitId: String? = null
    private var activeVideoStartedAt = 0L
    private var activeVideoCandidateCount = 0
    private var activeVideoMotionScore = 0f
    private var recordingStopRequested = false
    private var clipsRecorded = 0
    private var clipsUploaded = 0
    private var clipsDiscarded = 0
    private var videoUnavailableReason: String? = null
    private var commandPollInProgress = false
    private var commandsHandled = 0
    private var commandErrors = 0
    private var lastStatusPostAt = 0L
    private var latestMotionStats = MotionStats(
        score = 0f,
        threshold = 0.05f,
        consecutiveMotionFrames = 0,
        requiredConsecutiveFrames = 3,
        motionActive = false,
        sampleCount = 0,
    )
    private var visitState = VisitState.IDLE
    private var currentVisitId: String? = null
    private var visitCandidateCount = 0
    private var visitBestMotionScore = 0f
    private var visitLastMotionAt = 0L
    private var visitLastCaptureAt = 0L

    private val requestCameraPermission = registerForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            startCamera()
        } else {
            setStatus("Camera permission denied")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        setContentView(R.layout.activity_main)

        previewView = findViewById(R.id.previewView)
        roiOverlay = findViewById(R.id.roiOverlay)
        statusText = findViewById(R.id.statusText)
        debugStatsText = findViewById(R.id.debugStatsText)
        backendUrlInput = findViewById(R.id.backendUrlInput)
        deviceTokenInput = findViewById(R.id.deviceTokenInput)
        statusButton = findViewById(R.id.statusButton)
        retryButton = findViewById(R.id.retryButton)

        cameraExecutor = Executors.newSingleThreadExecutor()
        pendingUploadStore = PendingUploadStore(this)
        apiClient = BirdieApiClient(this)
        uploadsQueued = pendingUploadStore.list().size

        roiOverlay.roi = roi
        backendUrlInput.setText(loadBackendUrl())
        deviceTokenInput.setText(loadDeviceToken())

        statusButton.setOnClickListener {
            saveSettings()
            postDeviceStatus()
        }
        retryButton.setOnClickListener {
            saveSettings()
            retryPendingUploads()
        }
        startRemoteControlLoop()

        if (hasCameraPermission()) {
            startCamera()
        } else {
            requestCameraPermission.launch(Manifest.permission.CAMERA)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        remoteLoopJob?.cancel()
        stopVisitRecording(visitCandidateCount)
        cameraExecutor.shutdown()
    }

    private fun startCamera() {
        val cameraProviderFuture = ProcessCameraProvider.getInstance(this)
        cameraProviderFuture.addListener(
            {
                val cameraProvider = cameraProviderFuture.get()
                val preview = Preview.Builder().build().also {
                    it.setSurfaceProvider(previewView.surfaceProvider)
                }
                val imageCaptureUseCase = ImageCapture.Builder()
                    .setCaptureMode(ImageCapture.CAPTURE_MODE_MINIMIZE_LATENCY)
                    .build()
                imageCapture = imageCaptureUseCase
                val videoCaptureUseCase = VideoCapture.withOutput(
                    Recorder.Builder()
                        .setQualitySelector(QualitySelector.from(Quality.SD))
                        .build(),
                )
                videoCapture = videoCaptureUseCase
                videoUnavailableReason = null
                val analysis = ImageAnalysis.Builder()
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                    .also {
                        it.setAnalyzer(
                            cameraExecutor,
                            MotionAnalyzer(
                                roi = roi,
                                threshold = MOTION_THRESHOLD,
                                requiredConsecutiveFrames = MOTION_REQUIRED_FRAMES,
                                onStats = ::onMotionStats,
                            ),
                        )
                    }

                try {
                    cameraProvider.unbindAll()
                    try {
                        cameraProvider.bindToLifecycle(
                            this,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            imageCaptureUseCase,
                            videoCaptureUseCase,
                            analysis,
                        )
                    } catch (videoExc: Exception) {
                        cameraProvider.unbindAll()
                        videoCapture = null
                        videoUnavailableReason = videoExc.message ?: "not supported"
                        cameraProvider.bindToLifecycle(
                            this,
                            CameraSelector.DEFAULT_BACK_CAMERA,
                            preview,
                            imageCaptureUseCase,
                            analysis,
                        )
                    }
                    val pendingCount = pendingUploadStore.list().size
                    if (videoCapture == null) {
                        setStatus("Camera running without video: $videoUnavailableReason")
                    } else {
                        setStatus("Camera running; pending uploads: $pendingCount")
                    }
                    postDeviceStatus()
                    retryPendingUploads(reportEmpty = false)
                } catch (exc: Exception) {
                    setStatus("Camera start failed: ${exc.message}")
                }
            },
            ContextCompat.getMainExecutor(this),
        )
    }

    private fun captureVisitCandidate(
        motionScore: Float,
        visitId: String,
        candidateIndex: Int,
    ) {
        val imageCapture = imageCapture ?: return
        if (captureInProgress) return
        captureInProgress = true
        capturesStarted += 1
        runOnUiThread { updateDebugStats() }

        val tempFile = File(cacheDir, "birdie-capture-${System.currentTimeMillis()}.jpg")
        val outputOptions = ImageCapture.OutputFileOptions.Builder(tempFile).build()
        imageCapture.takePicture(
            outputOptions,
            cameraExecutor,
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                    val pending = pendingUploadStore.createImage(
                        imageFile = tempFile,
                        capturedAt = Instant.now(),
                        motionScore = motionScore,
                        visitId = visitId,
                        candidateIndex = candidateIndex,
                    )
                    tempFile.delete()
                    runOnUiThread {
                        captureInProgress = false
                        visitCandidateCount = maxOf(visitCandidateCount, candidateIndex + 1)
                        visitBestMotionScore = maxOf(visitBestMotionScore, motionScore)
                        uploadsQueued = pendingUploadStore.list().size
                        setStatus(
                            "Visit ${visitState.label}; uploading ${candidateIndex + 1}/$VISIT_MAX_CANDIDATES",
                        )
                        updateDebugStats()
                        uploadPending(pending)
                    }
                }

                override fun onError(exception: ImageCaptureException) {
                    tempFile.delete()
                    runOnUiThread {
                        captureInProgress = false
                        setStatus("Capture failed: ${exception.message}")
                        updateDebugStats()
                    }
                }
            },
        )
    }

    private fun captureCommandSnapshot(commandId: String) {
        val imageCapture = imageCapture
        if (imageCapture == null) {
            failRemoteCommand(commandId, "Camera is not ready")
            return
        }
        if (captureInProgress) {
            failRemoteCommand(commandId, "Camera capture is busy")
            return
        }
        captureInProgress = true
        capturesStarted += 1
        runOnUiThread { updateDebugStats() }

        val tempFile = File(cacheDir, "birdie-command-${System.currentTimeMillis()}.jpg")
        val outputOptions = ImageCapture.OutputFileOptions.Builder(tempFile).build()
        imageCapture.takePicture(
            outputOptions,
            cameraExecutor,
            object : ImageCapture.OnImageSavedCallback {
                override fun onImageSaved(outputFileResults: ImageCapture.OutputFileResults) {
                    val pending = pendingUploadStore.createCommandSnapshot(
                        imageFile = tempFile,
                        capturedAt = Instant.now(),
                        motionScore = latestMotionStats.score.coerceIn(0f, 1f),
                        commandId = commandId,
                    )
                    tempFile.delete()
                    runOnUiThread {
                        captureInProgress = false
                        commandsHandled += 1
                        uploadsQueued = pendingUploadStore.list().size
                        setStatus("Remote snapshot captured; uploading")
                        updateDebugStats()
                        uploadPending(pending)
                    }
                }

                override fun onError(exception: ImageCaptureException) {
                    tempFile.delete()
                    runOnUiThread {
                        captureInProgress = false
                        commandErrors += 1
                        setStatus("Remote snapshot failed: ${exception.message}")
                        updateDebugStats()
                    }
                    failRemoteCommand(commandId, exception.message ?: "Capture failed")
                }
            },
        )
    }

    private fun startRemoteControlLoop() {
        if (remoteLoopJob != null) return
        remoteLoopJob = lifecycleScope.launch {
            while (isActive) {
                val now = System.currentTimeMillis()
                if (now - lastStatusPostAt >= STATUS_POST_INTERVAL_MILLIS) {
                    lastStatusPostAt = now
                    postDeviceStatus(reportResult = false)
                }
                pollRemoteCommand()
                delay(COMMAND_POLL_INTERVAL_MILLIS)
            }
        }
    }

    private fun pollRemoteCommand() {
        if (commandPollInProgress) return
        commandPollInProgress = true
        lifecycleScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    apiClient.nextCommand(
                        backendUrl = backendUrl(),
                        deviceToken = deviceToken(),
                        deviceId = deviceId(),
                    )
                }
            }
            commandPollInProgress = false
            result.onSuccess { command ->
                command?.let { executeRemoteCommand(it) }
                updateDebugStats()
            }.onFailure {
                updateDebugStats()
            }
        }
    }

    private fun executeRemoteCommand(command: RemoteCommand) {
        when (command.command) {
            "snapshot" -> captureCommandSnapshot(command.id)
            "status" -> postDeviceStatus(reportResult = true)
            else -> {
                commandErrors += 1
                failRemoteCommand(command.id, "Unsupported command: ${command.command}")
                updateDebugStats()
            }
        }
    }

    private fun failRemoteCommand(commandId: String, message: String) {
        lifecycleScope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    apiClient.completeCommand(
                        backendUrl = backendUrl(),
                        deviceToken = deviceToken(),
                        commandId = commandId,
                        status = "failed",
                        errorMessage = message,
                    )
                }
            }
        }
    }

    private fun handleVisitFrame(stats: MotionStats, now: Long = System.currentTimeMillis()) {
        maybeStopRecordingAtLimit(now)

        if (stats.motionActive) {
            if (visitState == VisitState.IDLE) {
                startVisit(now)
            }
            visitState = VisitState.ACTIVE
            visitLastMotionAt = now
            maybeCaptureVisitCandidate(stats.score.coerceIn(0f, 1f), now)
            return
        }

        if (visitState == VisitState.IDLE) return

        visitState = VisitState.SETTLING
        if (!captureInProgress && now - visitLastMotionAt >= VISIT_QUIET_TIMEOUT_MILLIS) {
            finishVisit()
        }
    }

    private fun startVisit(now: Long) {
        visitState = VisitState.ACTIVE
        currentVisitId = UUID.randomUUID().toString()
        visitCandidateCount = 0
        visitBestMotionScore = 0f
        visitLastMotionAt = now
        visitLastCaptureAt = 0L
        startVisitRecording(currentVisitId.orEmpty(), now)
        setStatus("Visit started; recording clip")
    }

    private fun maybeCaptureVisitCandidate(motionScore: Float, now: Long) {
        val visitId = currentVisitId ?: return
        if (captureInProgress) return
        if (visitCandidateCount >= VISIT_MAX_CANDIDATES) return
        if (
            visitLastCaptureAt > 0L &&
            now - visitLastCaptureAt < VISIT_CAPTURE_INTERVAL_MILLIS
        ) {
            return
        }

        val candidateIndex = visitCandidateCount
        visitLastCaptureAt = now
        setStatus("Visit active; capturing ${candidateIndex + 1}/$VISIT_MAX_CANDIDATES")
        captureVisitCandidate(motionScore, visitId, candidateIndex)
    }

    private fun finishVisit() {
        val finishedVisitId = currentVisitId
        val uploadedCandidates = visitCandidateCount
        stopVisitRecording(uploadedCandidates)
        resetVisit()
        setStatus("Visit ended; sent $uploadedCandidates candidates for $finishedVisitId")
        updateDebugStats()
    }

    private fun startVisitRecording(visitId: String, now: Long) {
        if (activeRecording != null) return
        val videoCapture = videoCapture
        if (videoCapture == null) {
            videoUnavailableReason?.let { setStatus("Visit clip disabled: $it") }
            return
        }

        val clipFile = File(cacheDir, "birdie-visit-$visitId-$now.mp4")
        val outputOptions = FileOutputOptions.Builder(clipFile).build()
        activeVideoFile = clipFile
        activeVideoVisitId = visitId
        activeVideoStartedAt = now
        activeVideoCandidateCount = 0
        activeVideoMotionScore = 0f
        recordingStopRequested = false

        try {
            activeRecording = videoCapture.output
                .prepareRecording(this, outputOptions)
                .start(ContextCompat.getMainExecutor(this)) { event ->
                    onVideoRecordEvent(event)
                }
        } catch (exc: Exception) {
            activeRecording = null
            activeVideoFile = null
            activeVideoVisitId = null
            activeVideoStartedAt = 0L
            activeVideoMotionScore = 0f
            recordingStopRequested = false
            videoRecording = false
            clipFile.delete()
            clipsDiscarded += 1
            setStatus("Video recording failed: ${exc.message}")
            updateDebugStats()
        }
    }

    private fun stopVisitRecording(candidateCount: Int) {
        val recording = activeRecording ?: return
        if (recordingStopRequested) return
        activeVideoCandidateCount = candidateCount
        activeVideoMotionScore = visitBestMotionScore
        recordingStopRequested = true
        try {
            recording.stop()
        } catch (exc: Exception) {
            activeRecording = null
            videoRecording = false
            activeVideoFile?.delete()
            activeVideoFile = null
            activeVideoVisitId = null
            activeVideoStartedAt = 0L
            activeVideoCandidateCount = 0
            activeVideoMotionScore = 0f
            recordingStopRequested = false
            clipsDiscarded += 1
            setStatus("Video stop failed: ${exc.message}")
            updateDebugStats()
        }
    }

    private fun maybeStopRecordingAtLimit(now: Long) {
        if (activeRecording == null || recordingStopRequested || activeVideoStartedAt == 0L) {
            return
        }
        if (now - activeVideoStartedAt >= VISIT_MAX_RECORDING_MILLIS) {
            stopVisitRecording(visitCandidateCount)
            setStatus("Visit clip capped at ${VISIT_MAX_RECORDING_MILLIS / 1000}s")
        }
    }

    private fun onVideoRecordEvent(event: VideoRecordEvent) {
        when (event) {
            is VideoRecordEvent.Start -> {
                videoRecording = true
                updateDebugStats()
            }

            is VideoRecordEvent.Finalize -> {
                finishVideoRecording(event)
            }
        }
    }

    private fun finishVideoRecording(event: VideoRecordEvent.Finalize) {
        val clipFile = activeVideoFile
        val visitId = activeVideoVisitId
        val candidateCount = activeVideoCandidateCount
        val motionScore = activeVideoMotionScore
        activeRecording = null
        activeVideoFile = null
        activeVideoVisitId = null
        activeVideoStartedAt = 0L
        activeVideoCandidateCount = 0
        activeVideoMotionScore = 0f
        recordingStopRequested = false
        videoRecording = false

        if (event.hasError()) {
            clipFile?.delete()
            clipsDiscarded += 1
            setStatus("Video discarded: recorder error ${event.error}")
            updateDebugStats()
            return
        }
        if (clipFile == null || !clipFile.exists() || clipFile.length() <= 0L) {
            clipFile?.delete()
            clipsDiscarded += 1
            setStatus("Video discarded: empty clip")
            updateDebugStats()
            return
        }
        if (visitId.isNullOrBlank() || candidateCount <= 0) {
            clipFile.delete()
            clipsDiscarded += 1
            setStatus("Video discarded: no candidate frames")
            updateDebugStats()
            return
        }

        val pending = pendingUploadStore.createVideo(
            videoFile = clipFile,
            capturedAt = Instant.now(),
            motionScore = motionScore.coerceIn(0f, 1f),
            visitId = visitId,
        )
        clipFile.delete()
        clipsRecorded += 1
        uploadsQueued = pendingUploadStore.list().size
        setStatus("Visit video queued; uploading clip")
        updateDebugStats()
        uploadPending(pending)
    }

    private fun resetVisit() {
        visitState = VisitState.IDLE
        currentVisitId = null
        visitCandidateCount = 0
        visitBestMotionScore = 0f
        visitLastMotionAt = 0L
        visitLastCaptureAt = 0L
    }

    private fun postDeviceStatus(reportResult: Boolean = true) {
        lifecycleScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    apiClient.postStatus(
                        backendUrl = backendUrl(),
                        deviceToken = deviceToken(),
                        deviceId = deviceId(),
                    )
                }
            }
            if (reportResult) {
                setStatus(
                    result.fold(
                        onSuccess = { "Status sent for ${it.optString("id", deviceId())}" },
                        onFailure = { "Status failed: ${it.message}" },
                    ),
                )
            }
        }
    }

    private fun retryPendingUploads(reportEmpty: Boolean = true) {
        val uploads = pendingUploadStore.list()
        uploadsQueued = uploads.size
        updateDebugStats()
        if (uploads.isEmpty()) {
            if (reportEmpty) {
                setStatus("No pending uploads")
            }
            return
        }
        uploads.forEach { uploadPending(it) }
    }

    private fun uploadPending(pendingUpload: PendingUpload) {
        lifecycleScope.launch {
            val result = runCatching {
                withContext(Dispatchers.IO) {
                    apiClient.upload(
                        backendUrl = backendUrl(),
                        deviceToken = deviceToken(),
                        deviceId = deviceId(),
                        roi = roi,
                        pendingUpload = pendingUpload,
                    )
                }
            }
            result.onSuccess { response ->
                pendingUploadStore.markUploaded(pendingUpload)
                uploadsSucceeded += 1
                if (pendingUpload.kind == PendingUploadStore.KIND_VISIT_VIDEO) {
                    clipsUploaded += 1
                }
                uploadsQueued = pendingUploadStore.list().size
                setStatus(uploadSuccessStatus(response, pendingUpload))
                updateDebugStats()
            }.onFailure {
                uploadsQueued = pendingUploadStore.list().size
                setStatus("Upload queued: ${it.message}")
                updateDebugStats()
            }
        }
    }

    private fun onMotionStats(stats: MotionStats) {
        runOnUiThread {
            latestMotionStats = stats
            handleVisitFrame(stats)
            updateDebugStats()
        }
    }

    private fun updateDebugStats() {
        val stats = latestMotionStats
        val now = System.currentTimeMillis()
        val quietMillis = when {
            visitState == VisitState.IDLE -> 0L
            stats.motionActive -> 0L
            else -> (now - visitLastMotionAt).coerceAtLeast(0L)
        }
        val nextCaptureMillis = when {
            visitState == VisitState.IDLE -> 0L
            captureInProgress -> 0L
            visitCandidateCount >= VISIT_MAX_CANDIDATES -> 0L
            visitLastCaptureAt == 0L -> 0L
            else -> (VISIT_CAPTURE_INTERVAL_MILLIS - (now - visitLastCaptureAt)).coerceAtLeast(0L)
        }
        val clipMillis = if (activeVideoStartedAt > 0L) {
            (now - activeVideoStartedAt).coerceAtLeast(0L)
        } else {
            0L
        }
        val clipState = when {
            recordingStopRequested -> "saving"
            videoRecording -> "rec"
            videoCapture == null -> "off"
            else -> "ready"
        }
        debugStatsText.text = buildString {
            append("motion ")
            append("%.3f".format(stats.score))
            append(" / ")
            append("%.3f".format(stats.threshold))
            append(if (stats.motionActive) " active" else " quiet")
            append("  frames ")
            append(stats.consecutiveMotionFrames)
            append("/")
            append(stats.requiredConsecutiveFrames)
            append("\n")
            append("visit ")
            append(visitState.label)
            append("  candidates ")
            append(visitCandidateCount)
            append("/")
            append(VISIT_MAX_CANDIDATES)
            append("  best motion ")
            append("%.3f".format(visitBestMotionScore))
            append("\n")
            append("clip ")
            append(clipState)
            append(" ")
            append("%.1f".format(clipMillis / 1000.0))
            append("/")
            append("%.0fs".format(VISIT_MAX_RECORDING_MILLIS / 1000.0))
            append("  rec ")
            append(clipsRecorded)
            append("  up ")
            append(clipsUploaded)
            append("  drop ")
            append(clipsDiscarded)
            append("\n")
            append("cmd ")
            append(if (commandPollInProgress) "poll" else "idle")
            append("  ok ")
            append(commandsHandled)
            append("  err ")
            append(commandErrors)
            append("\n")
            append("quiet ")
            append("%.1f".format(quietMillis / 1000.0))
            append("/")
            append("%.1fs".format(VISIT_QUIET_TIMEOUT_MILLIS / 1000.0))
            append("  next ")
            append("%.1fs".format(nextCaptureMillis / 1000.0))
            append("  ")
            append("samples ")
            append(stats.sampleCount)
            append("  captures ")
            append(capturesStarted)
            append("  uploads ")
            append(uploadsSucceeded)
            append("  queued ")
            append(uploadsQueued)
        }
    }

    private fun uploadSuccessStatus(response: JSONObject, pendingUpload: PendingUpload): String {
        val status = response.optString("classification_status", "unknown")
        val label = response.optString("display_label", "species uncertain")
        val candidateCount = response.optInt("candidate_count", 1)
        val bestIndex = response.optInt("best_candidate_index", -1)
        val bestText = if (bestIndex >= 0) ", best ${bestIndex + 1}" else ""
        if (pendingUpload.kind == PendingUploadStore.KIND_VISIT_VIDEO) {
            return "Visit video uploaded: $label ($candidateCount candidates$bestText)"
        }
        if (pendingUpload.kind == PendingUploadStore.KIND_COMMAND_SNAPSHOT) {
            return "Remote snapshot uploaded: $label"
        }
        return "Uploaded: $status, $label ($candidateCount candidates$bestText)"
    }

    private fun hasCameraPermission(): Boolean {
        return ContextCompat.checkSelfPermission(this, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
    }

    private fun setStatus(message: String) {
        statusText.text = message
    }

    private fun backendUrl(): String = backendUrlInput.text.toString().ifBlank { DEFAULT_BACKEND_URL }

    private fun deviceToken(): String? = deviceTokenInput.text.toString().takeIf { it.isNotBlank() }

    private fun saveSettings() {
        getPreferences(Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_BACKEND_URL, backendUrl())
            .putString(KEY_DEVICE_TOKEN, deviceTokenInput.text.toString())
            .apply()
    }

    private fun loadBackendUrl(): String {
        val saved = getPreferences(Context.MODE_PRIVATE).getString(KEY_BACKEND_URL, DEFAULT_BACKEND_URL)
            ?: DEFAULT_BACKEND_URL
        if (saved.startsWith("http://127.0.0.1") || saved.startsWith("http://localhost")) {
            return DEFAULT_BACKEND_URL
        }
        return saved
    }

    private fun loadDeviceToken(): String {
        return getPreferences(Context.MODE_PRIVATE).getString(KEY_DEVICE_TOKEN, "") ?: ""
    }

    private fun deviceId(): String {
        val androidId = Settings.Secure.getString(contentResolver, Settings.Secure.ANDROID_ID)
        val model = "${Build.MANUFACTURER}-${Build.MODEL}"
            .lowercase()
            .replace(Regex("[^a-z0-9]+"), "-")
            .trim('-')
            .ifBlank { "android-phone" }
        return "$model-$androidId"
    }

    companion object {
        private const val DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"
        private const val KEY_BACKEND_URL = "backend_url"
        private const val KEY_DEVICE_TOKEN = "device_token"
        private const val MOTION_THRESHOLD = 0.05f
        private const val MOTION_REQUIRED_FRAMES = 3
        private const val COMMAND_POLL_INTERVAL_MILLIS = 10_000L
        private const val STATUS_POST_INTERVAL_MILLIS = 60_000L
        private const val VISIT_CAPTURE_INTERVAL_MILLIS = 2_000L
        private const val VISIT_QUIET_TIMEOUT_MILLIS = 8_000L
        private const val VISIT_MAX_RECORDING_MILLIS = 30_000L
        private const val VISIT_MAX_CANDIDATES = 4
    }
}
