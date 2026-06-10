package com.birdie.camera

data class Roi(
    val x: Float,
    val y: Float,
    val width: Float,
    val height: Float,
) {
    companion object {
        val Default = Roi(x = 0.03f, y = 0.46f, width = 0.92f, height = 0.34f)
    }
}
