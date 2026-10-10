@echo off
call "C:\Program Files\Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars32.bat" >nul
cd /d "%~dp0"
if not exist build mkdir build
cl /nologo /std:c++17 /EHsc /O2 /MD /w /bigobj ^
  /I shim /I EASTL\include /I EABase\include\Common ^
  AnimTest\src\animtest.cpp EASTL\source\*.cpp ^
  /Fo:build\ /Fe:build\animtest.exe 2>&1
