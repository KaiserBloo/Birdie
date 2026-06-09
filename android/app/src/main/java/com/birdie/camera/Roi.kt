package com.birdie.camera

data class Roi(
    val x: Float,
    val y: Float,
    val width: Float,
    val height: Float,
) {
    companion object {
        val Default = Roi(x = 0.05f, y = 0.48f, width = 0.88f, height = 0.28f)
    }
}
