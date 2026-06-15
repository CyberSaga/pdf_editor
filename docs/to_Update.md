## 問題修復
* 將所有工作流程都加速（包含：開啟視窗時間、開啟檔案時間）
-> 查明根本成因並修復

## 做法修改：
* 點選旋轉鈕是將物件轉動到 90°、180°、270°、360° → OK
* 旋轉頁面要轉多少角度應該是用選單 → OK
* 將全螢幕從"常用"中取消，只要留右邊快速選項的"全螢幕"就夠了 → OK
* 繪製矩形，滑鼠在拖曳的時候就要同步顯示出將會拉出的矩形/方框的預覽 → OK
* 要可以更彈性的將視窗縮得更小，且可以斜線縮放
* 縮圖要在縮圖列表內置中，且隨著左側邊欄的縮放而縮放大小
* 文件要在文件閱讀區置中
-> 提出建議新做法並實作

## 功能新增：
* 新增快捷鍵 F1：跳回瀏覽模式 → OK
* 依奇數頁、偶數頁來刪除、旋轉頁面 → OK
* 可以做為開啟檔案的預設應用程式，圖示就用 Windows 預設的 PDF icon → OK
* 頁數要改成輸入框，輸入數字就跳到該頁 → OK
* 從檔案匯入頁時，若被匯入的檔案有密碼保護，也要跳出密碼輸入框來解鎖（合併檔案已經有密碼輸入框） → OK
* 刪除頁、旋轉頁的範圍也要多一個「自訂」
* 當連點兩下打開 PDF 檔時，若已有視窗實例存在，要使該視窗實例浮現到畫面最上層
-> 提出建議的實現方法並實作

## 待釐清（未必是錯誤）：
* 為何拉正頁面後檔案大小變超大 → 已釐清，要使用者手動最佳化

the .venv build env still has Pillow 12.1.1 and now-also-needed numpy isn't installed there — so before the next PyInstaller build, run .venv\Scripts\python -m pip install -U "Pillow>=12.2.0" numpy and rebuild, so the shipped artifact matches the secured requirements.txt.
