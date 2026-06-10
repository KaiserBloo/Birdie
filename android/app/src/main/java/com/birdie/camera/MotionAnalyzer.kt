package com.birdie.camera

import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

data class MotionStats(
    val score: Float,
    val threshold: Float,
    val consecutiveMotionFrames: Int,
    val requiredConsecutiveFrames: Int,
    val motionActive: Boolean,
    val sampleCount: Int,
)

class MotionAnalyzer(
    private val roi: Roi,
    private val threshold: Float = 0.042f,
    private val requiredConsecutiveFrames: Int = 2,
    private val minIntervalMillis: Long = 250L,
    private val onStats: (MotionStats) -> Unit,
) : ImageAnalysis.Analyzer {
    private var previousSample: ByteArray? = null
    private var consecutiveMotionFrames = 0
    private var lastAnalyzedAt = 0L

    override fun analyze(image: ImageProxy) {
        try {
            val now = System.currentTimeMillis()
            if (now - lastAnalyzedAt < minIntervalMillis) return
            lastAnalyzedAt = now

            val sample = sampleRoiLuma(image, roi)
            val previous = previousSample
            previousSample = sample
            if (previous == null || previous.size != sample.size) {
                publishStats(score = 0f, sampleCount = sample.size)
                return
            }

            val score = motionScore(previous, sample)
            if (score >= threshold) {
                consecutiveMotionFrames += 1
            } else {
                consecutiveMotionFrames = 0
            }
            publishStats(score = score, sampleCount = sample.size)
        } finally {
            image.close()
        }
    }

    private fun sampleRoiLuma(image: ImageProxy, roi: Roi): ByteArray {
        val plane = image.planes[0]
        val buffer = plane.buffer
        val rowStride = plane.rowStride
        val pixelStride = plane.pixelStride

        val left = (roi.x * image.width).toInt().coerceIn(0, image.width - 1)
        val top = (roi.y * image.height).toInt().coerceIn(0, image.height - 1)
        val right = ((roi.x + roi.width) * image.width).toInt().coerceIn(left + 1, image.width)
        val bottom = ((roi.y + roi.height) * image.height).toInt().coerceIn(top + 1, image.height)
        val stepX = max(1, (right - left) / 48)
        val stepY = max(1, (bottom - top) / 36)

        val values = ArrayList<Byte>(48 * 36)
        var y = top
        while (y < bottom) {
            var x = left
            while (x < right) {
                val index = y * rowStride + x * pixelStride
                if (index < buffer.limit()) {
                    values.add(buffer.get(index))
                }
                x += stepX
            }
            y += stepY
        }
        return values.toByteArray()
    }

    private fun motionScore(previous: ByteArray, current: ByteArray): Float {
        val count = min(previous.size, current.size)
        if (count == 0) return 0f
        var totalDifference = 0L
        for (index in 0 until count) {
            val previousValue = previous[index].toInt() and 0xff
            val currentValue = current[index].toInt() and 0xff
            totalDifference += abs(previousValue - currentValue)
        }
        return totalDifference.toFloat() / (count * 255f)
    }

    private fun publishStats(score: Float, sampleCount: Int) {
        onStats(
            MotionStats(
                score = score,
                threshold = threshold,
                consecutiveMotionFrames = consecutiveMotionFrames,
                requiredConsecutiveFrames = requiredConsecutiveFrames,
                motionActive = consecutiveMotionFrames >= requiredConsecutiveFrames,
                sampleCount = sampleCount,
            ),
        )
    }
}
