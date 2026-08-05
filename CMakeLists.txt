########################################################################
# Project setup
########################################################################
cmake_minimum_required(VERSION 3.10)
project(gr-op25 CXX C)
enable_testing()

#policy setup
cmake_policy(SET CMP0011 NEW)
cmake_policy(SET CMP0012 NEW)
# CMP0026 (LOCATION target property) and CMP0045 (non-existent targets in
# get_target_property) were both deprecated in CMake 3.0 and their OLD
# behaviour has been removed. The codebase does not rely on either.

set_property(GLOBAL PROPERTY ALLOW_DUPLICATE_CUSTOM_TARGETS 1)

#select the release build type by default to get optimization flags
if(NOT CMAKE_BUILD_TYPE)
   set(CMAKE_BUILD_TYPE "Release")
   message(STATUS "Build type not specified: defaulting to Release.")
else()
   message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
endif(NOT CMAKE_BUILD_TYPE)
set(CMAKE_BUILD_TYPE ${CMAKE_BUILD_TYPE} CACHE STRING "")

# Disable Documentation
add_definitions(-DENABLE_DOXYGEN=OFF)

########################################################################
# Compiler specific setup
########################################################################
if((CMAKE_CXX_COMPILER_ID MATCHES "Clang" OR
    CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    AND NOT WIN32)
    #http://gcc.gnu.org/wiki/Visibility
    set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -fvisibility=hidden")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fvisibility=hidden")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -fvisibility-inlines-hidden")
endif()

if(CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    set(CMAKE_CXX_STANDARD 17)
elseif(CMAKE_CXX_COMPILER_ID MATCHES "Clang")
    set(CMAKE_CXX_STANDARD 17)
elseif(CMAKE_CXX_COMPILER_ID STREQUAL "MSVC")
    set(CMAKE_CXX_STANDARD 17)
else()
    message(WARNING "C++ standard could not be set because compiler is not GNU, Clang or MSVC.")
endif()

# Misc options
if(NOT CMAKE_BUILD_TYPE STREQUAL "Release" AND
   (CMAKE_CXX_COMPILER_ID MATCHES "Clang" OR
    CMAKE_CXX_COMPILER_ID STREQUAL "GNU"))
    message(STATUS "Enabling enhanced compiler warnings for Non-Release build type")
    add_definitions(-Wall)
    add_definitions(-Wextra)
    add_definitions(-Wsign-compare)
    add_definitions(-Wno-unused-parameter)
    add_definitions(-Wno-unused-function)
    add_definitions(-Wno-missing-field-initializers)
    add_definitions(-Werror=return-type)
    #add_definitions(-Wconversion)
    #add_definitions(-pedantic)
    #add_definitions(-ansi)
endif()

# SIMD
if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|AMD64|x86")
    set(USE_SIMD "SSE2" CACHE STRING "Use SIMD instructions")
else()
    set(USE_SIMD "no" CACHE STRING "Use SIMD instructions")
endif()
set(USE_SIMD_VALUES "no" "SSE2" "AVX")
set_property(CACHE USE_SIMD PROPERTY STRINGS ${USE_SIMD_VALUES})
list(FIND USE_SIMD_VALUES ${USE_SIMD} USE_SIMD_INDEX)
if(${USE_SIMD_INDEX} EQUAL -1)
    message(FATAL_ERROR "Option ${USE_SIMD} not supported, valid entries are ${USE_SIMD_VALUES}")
endif()

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang" OR
    CMAKE_CXX_COMPILER_ID STREQUAL "GNU")
    if(USE_SIMD MATCHES SSE2)
        add_definitions(-msse2)
        add_definitions(-DUSE_SSE2)
    endif()
    if(USE_SIMD MATCHES AVX)
        add_definitions(-march=native)
        add_definitions(-DUSE_AVX)
    endif()
elseif(CMAKE_CXX_COMPILER_ID STREQUAL "MSVC")
    if(USE_SIMD MATCHES SSE2)
        add_definitions(/arch:SSE2)
        add_definitions(-DUSE_SSE2)
    endif()
    if(USE_SIMD MATCHES AVX)
        add_definitions(/arch:AVX)
        add_definitions(-DUSE_AVX)
    endif()
endif()

########################################################################
# Find boost
########################################################################
#if(UNIX AND EXISTS "/usr/lib64")
#    list(APPEND BOOST_LIBRARYDIR "/usr/lib64") #fedora 64-bit fix
#endif(UNIX AND EXISTS "/usr/lib64")
#set(Boost_ADDITIONAL_VERSIONS
#    "1.35.0" "1.35" "1.36.0" "1.36" "1.37.0" "1.37" "1.38.0" "1.38" "1.39.0" "1.39"
#    "1.40.0" "1.40" "1.41.0" "1.41" "1.42.0" "1.42" "1.43.0" "1.43" "1.44.0" "1.44"
#    "1.45.0" "1.45" "1.46.0" "1.46" "1.47.0" "1.47" "1.48.0" "1.48" "1.49.0" "1.49"
#    "1.50.0" "1.50" "1.51.0" "1.51" "1.52.0" "1.52" "1.53.0" "1.53" "1.54.0" "1.54"
#    "1.55.0" "1.55" "1.56.0" "1.56" "1.57.0" "1.57" "1.58.0" "1.58" "1.59.0" "1.59"
#    "1.60.0" "1.60" "1.61.0" "1.61" "1.62.0" "1.62" "1.63.0" "1.63" "1.64.0" "1.64"
#    "1.65.0" "1.65" "1.66.0" "1.66" "1.67.0" "1.67" "1.68.0" "1.68" "1.69.0" "1.69"
#)
#find_package(Boost "1.35" COMPONENTS filesystem system)
#
#if(NOT Boost_FOUND)
#    message(FATAL_ERROR "Boost required to compile op25")
#endif()

########################################################################
# Find gnuradio build dependencies
########################################################################
list(APPEND CMAKE_MODULE_PATH ${CMAKE_SOURCE_DIR}/cmake/Modules)
# CMAKE_CXX_STANDARD 17 is already set above; the explicit -std= flag is
# redundant and can conflict with some toolchain wrappers.
find_package(CppUnit)
if(NOT CPPUNIT_FOUND)
    message(FATAL_ERROR "CppUnit required to compile op25")
endif()
# GnuradioRuntime was the pre-3.8 find module; GNURadio 3.10+ uses only
# find_package(Gnuradio).
find_package(Gnuradio "3.10" REQUIRED)
MESSAGE(STATUS "GnuRadio version ${Gnuradio_VERSION}")
# Python 2 and GNURadio < 3.8 are no longer supported; the sub-projects
# both require GNURadio 3.10 which always uses Python 3.
set(OP25_PYTHON_VER 3)
MESSAGE(STATUS "Configuring for Python ${OP25_PYTHON_VER}")

# Use cmake's cross-platform path search instead of a hardcoded Linux path.
# Modern spdlog installations (Homebrew, Ubuntu 22+) ship fmt separately.
find_path(SPDLOG_FMT_BUNDLED_INCLUDE "spdlog/fmt/bundled/core.h")
if(NOT SPDLOG_FMT_BUNDLED_INCLUDE)
    ADD_DEFINITIONS(-DSPDLOG_FMT_EXTERNAL=1)
endif()

# Determine the Python site-packages directory relative to the install prefix.
# distutils.sysconfig was deprecated in Python 3.10 and removed in Python 3.12;
# the stdlib sysconfig module is the correct replacement.
execute_process(COMMAND python3 -c "
import sys, sysconfig
# get_path with empty base/platbase returns the path relative to a prefix.
rel = sysconfig.get_path('platlib', vars={'platbase': '', 'base': ''}).lstrip('/')
print(rel)
" OUTPUT_VARIABLE OP25_PYTHON_DIR OUTPUT_STRIP_TRAILING_WHITESPACE
)
MESSAGE(STATUS "OP25_PYTHON_DIR has been set to \"${OP25_PYTHON_DIR}\".")

add_subdirectory(op25/gr-op25)
add_subdirectory(op25/gr-op25_repeater)

########################################################################
# Create uninstall target
########################################################################
configure_file(
    ${CMAKE_SOURCE_DIR}/cmake/cmake_uninstall.cmake.in
    ${CMAKE_CURRENT_BINARY_DIR}/cmake_uninstall.cmake
@ONLY)

add_custom_target(uninstall
    ${CMAKE_COMMAND} -P ${CMAKE_CURRENT_BINARY_DIR}/cmake_uninstall.cmake
)
