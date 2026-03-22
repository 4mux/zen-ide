#pragma once

#include <cmath>
#include <functional>
#include <iostream>
#include <stdexcept>
#include <string>

namespace test {

static int passed = 0;
static int failed = 0;

inline void describe(const std::string& name, std::function<void()> fn) {
    std::cout << "\n" << name << "\n";
    fn();
}

inline void it(const std::string& name, std::function<void()> fn) {
    try {
        fn();
        std::cout << "  \u2713 " << name << "\n";
        ++passed;
    } catch (const std::exception& e) {
        std::cout << "  \u2717 " << name << " \xe2\x80\x94 " << e.what() << "\n";
        ++failed;
    }
}

template <typename A, typename B>
inline void expect_eq(A a, B b, const char* file, int line) {
    if (!(a == b))
        throw std::runtime_error(std::string("expected equal at ") + file + ":" + std::to_string(line));
}

inline void expect_near(double a, double b, double eps, const char* file, int line) {
    if (std::abs(a - b) > eps)
        throw std::runtime_error(
            std::string("expected ") + std::to_string(a) + " \xe2\x89\x88 " + std::to_string(b) +
            " (diff=" + std::to_string(std::abs(a - b)) + ") at " + file + ":" + std::to_string(line));
}

inline void expect_true(bool cond, const char* file, int line) {
    if (!cond)
        throw std::runtime_error(std::string("expected true at ") + file + ":" + std::to_string(line));
}

inline int summary() {
    std::cout << "\n" << passed << " passed";
    if (failed) std::cout << ", " << failed << " failed";
    std::cout << "\n";
    return failed > 0 ? 1 : 0;
}

} // namespace test

#define EXPECT_EQ(a, b)           test::expect_eq((a), (b), __FILE__, __LINE__)
#define EXPECT_NEAR(a, b, eps)    test::expect_near((a), (b), (eps), __FILE__, __LINE__)
#define EXPECT_TRUE(cond)         test::expect_true((cond), __FILE__, __LINE__)
