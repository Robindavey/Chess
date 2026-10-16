@echo off
python -m venv .venv || exit /b 1
call .venv\Scripts\activate.bat
pip install flask || exit /b 1
g++ -O3 -march=native -std=c++20 game_board.cpp -o game_board.exe || exit /b 1
python app.py