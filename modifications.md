## Modifications:

* Clicking object's rotation button rotates the it to 90°, 180°, 270°, or 360° from its original angle, instead of adding or subtracting 90°, 180°, 270°, or 360° from its current angle.
* The page rotation angle should be selected using a menu: 90°, 180°, 270°, or 360°, with options for all(全部), odd pages(奇數頁), or even pages(偶數頁).
* When drawing a rectangle, a preview of the rectangle/box to be drawn should be displayed simultaneously while dragging the mouse.
-> Propose a new approach and implement it.

## New Features:

* Added a shortcut key F1: Return to browsing mode(瀏覽模式).
* Delete and rotate pages with options for all(全部), odd pages(奇數頁), or even pages(偶數頁).
* The page number/total page number display should be changed from a simple display to an input box; entering a number should jump to that page.
* When importing pages from file(從檔案匯入頁), if the file to be imported is password protected, a password input box should pop up to unlock it (merging files already has a password input box).

-> Proposed implementation method and implementation

## To be clarified (not necessarily an error):

* Why does the file size become excessively large after straightening the page?


The .venv build environment still has Pillow 12.1.1 and now-also-needed numpy isn't installed there — so before the next PyInstaller build, run .venv\Scripts\python -m pip install -U "Pillow>=12.2.0" numpy and rebuild, so the shipped artifact matches the secured requirements.txt.