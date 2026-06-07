## 問題修復
* 將所有工作流程都加速（包含：最佳化檔案速度、開啟檔案後換頁、列印送出後卡住電腦的時間）
-> 查明根本成因並修復

## 做法修改：
* 點選旋轉鈕是將物件轉動到 90°、180°、270°、360°
* 旋轉頁面要轉多少角度應該是用選單
* 將全螢幕從"常用"中取消，只要留右邊快速選項的"全螢幕"就夠了
-> 提出建議新做法並實作

## 功能新增：
* 新增快捷鍵：跳回瀏覽模式
* 依奇數頁、偶數頁來刪除、旋轉頁面
* 可以做為開啟檔案的預設應用程式，圖示就用 Windows 預設的 PDF icon

-> 提出建議的實現方法並實作

the .venv build env still has Pillow 12.1.1 and now-also-needed numpy isn't installed there — so before the next PyInstaller build, run .venv\Scripts\python -m pip install -U "Pillow>=12.2.0" numpy and rebuild, so the shipped artifact matches the secured requirements.txt.