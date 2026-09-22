cmake_minimum_required(VERSION 3.10)
project(dsp_host_xcore)
# octabam's dual-core dsp_host fork (refs/octabam/vendor/dsp56300/source/
# dsp_host/dsp_host.cpp, renamed dsp_host_xcore.cpp here), built as a SEPARATE
# target from our own single-core source/dsp_host/dsp_host.cpp -- the two
# files share a name upstream but are NOT interchangeable (this one adds
# -memB/-core/-skew dual-core hosting on top of the same dsp56kEmu library;
# see NOTES.md "Session 77" for why they must not collide).
add_executable(dsp_host_xcore dsp_host_xcore.cpp)
target_include_directories(dsp_host_xcore PRIVATE ${DSP56300_SOURCE})
target_link_libraries(dsp_host_xcore PRIVATE dsp56kEmu)
