package com.birdie.camera

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.util.AttributeSet
import android.view.View

class RoiOverlayView @JvmOverloads constructor(
    context: Context,
    attrs: AttributeSet? = null,
) : View(context, attrs) {
    var roi: Roi = Roi.Default
        set(value) {
            field = value
            invalidate()
        }

    private val maskPaint = Paint().apply {
        color = Color.argb(88, 0, 0, 0)
        style = Paint.Style.FILL
    }

    private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Color.rgb(68, 180, 112)
        style = Paint.Style.STROKE
        strokeWidth = 4f
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val rect = RectF(
            roi.x * width,
            roi.y * height,
            (roi.x + roi.width) * width,
            (roi.y + roi.height) * height,
        )
        canvas.drawRect(0f, 0f, width.toFloat(), rect.top, maskPaint)
        canvas.drawRect(0f, rect.bottom, width.toFloat(), height.toFloat(), maskPaint)
        canvas.drawRect(0f, rect.top, rect.left, rect.bottom, maskPaint)
        canvas.drawRect(rect.right, rect.top, width.toFloat(), rect.bottom, maskPaint)
        canvas.drawRect(rect, borderPaint)
    }
}
