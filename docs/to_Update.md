## 問題修復
* 將所有工作流程都加速（包含：最佳化檔案速度、開啟檔案後換頁、列印送出後卡住電腦的時間）
-> 查明根本成因並修復

## 做法修改：
* 點選旋轉鈕是將物件轉動到 90°、180°、270°、360°
* 旋轉頁面要轉多少角度應該是用選單
* 將全螢幕從"常用"中取消，只要留右邊快速選項的"全螢幕"就夠了
* 繪製矩形，滑鼠在拖曳的時候就要同步顯示出將會拉出的矩形/方框的預覽
-> 提出建議新做法並實作

## 功能新增：
* 新增快捷鍵 F1：跳回瀏覽模式
* 依奇數頁、偶數頁來刪除、旋轉頁面
* 可以做為開啟檔案的預設應用程式，圖示就用 Windows 預設的 PDF icon → OK
* 頁數要改成輸入框，輸入數字就跳到該頁
* 從檔案匯入頁時，若被匯入的檔案有密碼保護，也要跳出密碼輸入框來解鎖（合併檔案已經有密碼輸入框）
-> 提出建議的實現方法並實作

## 待釐清（未必是錯誤）：
* 為何拉正頁面後檔案大小變超大

the .venv build env still has Pillow 12.1.1 and now-also-needed numpy isn't installed there — so before the next PyInstaller build, run .venv\Scripts\python -m pip install -U "Pillow>=12.2.0" numpy and rebuild, so the shipped artifact matches the secured requirements.txt.

- Phase 2 note: print watermark overlays are now suppressed in `WatermarkTool.needs_page_overlay(...)` for `purpose == "print"`, so the helper subprocess remains the only print stamping path.
