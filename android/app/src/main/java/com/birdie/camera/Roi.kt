package com.birdie.camera

data class Roi(
    val x: Float,
    val y: Float,
    val width: Float,
    val height: Float,
) {
    companion object {
        val Default = Roi(x = 0.25f, y = 0.25f, width = 0.5f, height = 0.5f)
    }
}
