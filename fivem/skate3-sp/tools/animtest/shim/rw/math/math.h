// Minimal stand-in for RenderWare's rw::math (vpu = SIMD flavour: every vector type is 16 bytes, 16-aligned),
// covering only what AnimTest uses.
#pragma once
#include <cmath>

namespace rw { namespace math {

struct VecFloat {
    float v;
    VecFloat() : v(0) {}
    VecFloat(float f) : v(f) {}
    float GetFloat() const { return v; }
    operator float() const { return v; }
};

namespace vpu {
using rw::math::VecFloat;

struct alignas(16) Vector3 {
    float x, y, z, pad;
    Vector3() : x(0), y(0), z(0), pad(0) {}
    Vector3(float a, float b, float c) : x(a), y(b), z(c), pad(0) {}
    float GetX() const { return x; } float GetY() const { return y; } float GetZ() const { return z; }
    void SetX(float f) { x = f; } void SetY(float f) { y = f; } void SetZ(float f) { z = f; }
    Vector3 operator+(const Vector3& o) const { return Vector3(x + o.x, y + o.y, z + o.z); }
    Vector3 operator-(const Vector3& o) const { return Vector3(x - o.x, y - o.y, z - o.z); }
    Vector3 operator*(float s) const { return Vector3(x * s, y * s, z * s); }
};

struct alignas(16) Vector4 {
    float x, y, z, w;
    Vector4() : x(0), y(0), z(0), w(0) {}
    Vector4(float a, float b, float c, float d) : x(a), y(b), z(c), w(d) {}
    Vector4(const Vector3& v) : x(v.x), y(v.y), z(v.z), w(0) {}
    Vector4& operator=(const Vector3& v) { x = v.x; y = v.y; z = v.z; w = 0; return *this; }
    float GetX() const { return x; } float GetY() const { return y; } float GetZ() const { return z; }
    float GetW() const { return w; }
    void SetX(float f) { x = f; } void SetY(float f) { y = f; } void SetZ(float f) { z = f; }
    void SetW(float f) { w = f; }
    operator Vector3() const { return Vector3(x, y, z); }
};

struct alignas(16) Quaternion {
    float x, y, z, w;
    Quaternion() : x(0), y(0), z(0), w(1) {}
    Quaternion(float a, float b, float c, float d) : x(a), y(b), z(c), w(d) {}
    float GetX() const { return x; } float GetY() const { return y; } float GetZ() const { return z; }
    float GetW() const { return w; }
    void SetX(float f) { x = f; } void SetY(float f) { y = f; } void SetZ(float f) { z = f; }
    void SetW(float f) { w = f; }
    void Normalize() {
        float l = std::sqrt(x * x + y * y + z * z + w * w);
        if (l > 0) { x /= l; y /= l; z /= l; w /= l; }
    }
};

} } }

template <typename T> inline T Clamp(T v, T lo, T hi) { return v < lo ? lo : (v > hi ? hi : v); }
