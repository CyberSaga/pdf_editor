"""
改進的 PDF 文字編輯方法
避免編輯時清除其他文字方塊的內容

關鍵改進：
1. 精確定位目標文字塊（而非整個矩形）
2. 文字塊檢測與隔離
3. 插入前衝突檢測
4. 使用文字內容匹配而非僅依賴座標
"""

import fitz
import logging
from typing import List, Tuple, Optional, Dict
import difflib

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class ImprovedTextEditor:
    """改進的文字編輯器，避免影響其他文字塊"""
    
    def __init__(self, doc: fitz.Document):
        self.doc = doc
    
    def get_text_blocks_in_rect(self, page_num: int, rect: fitz.Rect) -> List[Dict]:
        """
        獲取矩形區域內的所有文字塊
        
        Returns:
            List[Dict]: 每個文字塊包含 {
                'rect': fitz.Rect,  # 文字塊邊界
                'text': str,        # 文字內容
                'words': List,      # 單詞列表
                'block_index': int  # 文字塊索引
            }
        """
        page = self.doc[page_num - 1]
        blocks = page.get_text("dict", flags=0)["blocks"]
        
        text_blocks = []
        for i, block in enumerate(blocks):
            if block.get('type') == 0:  # 文字塊
                block_rect = fitz.Rect(block["bbox"])
                # 檢查文字塊是否與矩形相交
                if block_rect.intersects(rect):
                    # 提取文字內容
                    text_content = []
                    words = []
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text_content.append(span.get("text", ""))
                            # 收集單詞位置
                            for word_bbox in span.get("bbox", []):
                                if len(word_bbox) >= 4:
                                    words.append(word_bbox)
                    
                    text_blocks.append({
                        'rect': block_rect,
                        'text': "".join(text_content),
                        'words': words,
                        'block_index': i
                    })
        
        return text_blocks
    
    def find_target_text_block(self, page_num: int, rect: fitz.Rect, 
                              original_text: Optional[str] = None) -> Optional[Dict]:
        """
        精確定位要編輯的目標文字塊
        
        Args:
            page_num: 頁碼
            rect: 粗略的矩形區域
            original_text: 原始文字內容（如果提供，用於精確匹配）
        
        Returns:
            目標文字塊的資訊，如果找不到則返回 None
        """
        page = self.doc[page_num - 1]
        text_blocks = self.get_text_blocks_in_rect(page_num, rect)
        
        if not text_blocks:
            logger.warning(f"在矩形 {rect} 中未找到任何文字塊")
            return None
        
        # 如果提供了原始文字，使用內容匹配
        if original_text:
            original_text_clean = "".join(original_text.strip().split())
            
            best_match = None
            best_similarity = 0.0
            
            for block in text_blocks:
                block_text_clean = "".join(block['text'].strip().split())
                similarity = difflib.SequenceMatcher(
                    None, original_text_clean, block_text_clean
                ).ratio()
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_match = block
            
            # 如果相似度足夠高，返回最佳匹配
            if best_match and best_similarity > 0.5:
                logger.debug(f"找到匹配文字塊，相似度: {best_similarity:.2f}")
                return best_match
        
        # 如果沒有提供原始文字，或匹配失敗，選擇與矩形中心最接近的文字塊
        rect_center = fitz.Point(rect.x0 + rect.width/2, rect.y0 + rect.height/2)
        
        best_block = None
        min_distance = float('inf')
        
        for block in text_blocks:
            block_center = fitz.Point(
                block['rect'].x0 + block['rect'].width/2,
                block['rect'].y0 + block['rect'].height/2
            )
            distance = abs(block_center.x - rect_center.x) + abs(block_center.y - rect_center.y)
            
            if distance < min_distance:
                min_distance = distance
                best_block = block
        
        return best_block
    
    def get_precise_text_bounds(self, page_num: int, text_block: Dict) -> fitz.Rect:
        """
        獲取文字塊的精確邊界（基於實際單詞位置）
        """
        if text_block['words']:
            # 使用單詞位置計算精確邊界
            x0 = min(word[0] for word in text_block['words'] if len(word) >= 4)
            y0 = min(word[1] for word in text_block['words'] if len(word) >= 4)
            x1 = max(word[2] for word in text_block['words'] if len(word) >= 4)
            y1 = max(word[3] for word in text_block['words'] if len(word) >= 4)
            return fitz.Rect(x0, y0, x1, y1)
        else:
            # 回退到文字塊邊界
            return text_block['rect']
    
    def check_insertion_conflict(self, page_num: int, insert_rect: fitz.Rect, 
                                 exclude_block: Optional[Dict] = None) -> List[Dict]:
        """
        檢查插入新文字時是否會與其他文字塊衝突
        
        Args:
            page_num: 頁碼
            insert_rect: 要插入文字的矩形區域
            exclude_block: 要排除的文字塊（通常是即將被清除的目標塊）
        
        Returns:
            衝突的文字塊列表
        """
        page = self.doc[page_num - 1]
        blocks = page.get_text("dict", flags=0)["blocks"]
        
        conflicts = []
        exclude_index = exclude_block['block_index'] if exclude_block else -1
        
        for block in blocks:
            if block.get('type') == 0:  # 文字塊
                block_index = blocks.index(block)
                
                # 跳過要排除的塊
                if block_index == exclude_index:
                    continue
                
                block_rect = fitz.Rect(block["bbox"])
                
                # 檢查是否與插入區域重疊
                if block_rect.intersects(insert_rect):
                    # 計算重疊面積
                    intersection = block_rect & insert_rect
                    overlap_ratio = (intersection.width * intersection.height) / \
                                   (block_rect.width * block_rect.height)
                    
                    # 如果重疊超過 10%，視為衝突
                    if overlap_ratio > 0.1:
                        text_content = []
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                text_content.append(span.get("text", ""))
                        
                        conflicts.append({
                            'rect': block_rect,
                            'text': "".join(text_content),
                            'overlap_ratio': overlap_ratio
                        })
        
        return conflicts
    
    def edit_text_safe(self, page_num: int, rect: fitz.Rect, new_text: str,
                      font: str = "helv", size: int = 12, 
                      color: tuple = (0.0, 0.0, 0.0),
                      original_text: Optional[str] = None) -> bool:
        """
        安全地編輯文字，避免影響其他文字塊
        
        改進點：
        1. 精確定位目標文字塊
        2. 只清除目標文字塊，而非整個矩形
        3. 插入前檢查衝突
        4. 使用精確的文字邊界
        """
        if not new_text.strip():
            logger.warning("文字內容為空，跳過編輯")
            return False
        
        page = self.doc[page_num - 1]
        
        # --- 步驟 1: 精確定位目標文字塊 ---
        target_block = self.find_target_text_block(page_num, rect, original_text)
        
        if not target_block:
            logger.warning(f"無法定位目標文字塊，使用原始矩形")
            # 回退到原始方法，但使用更精確的邊界
            precise_rect = self.doc[page_num - 1].get_text_bounds(page_num, rect)
            redact_rect = precise_rect
        else:
            # 使用精確的文字邊界
            redact_rect = self.get_precise_text_bounds(page_num, target_block)
            logger.debug(f"找到目標文字塊，精確邊界: {redact_rect}, 文字: '{target_block['text'][:30]}...'")
        
        # --- 步驟 2: 檢查插入區域是否會衝突 ---
        # 估算新文字需要的空間
        page_width = page.rect.width
        page_height = page.rect.height
        margin = 15
        max_allowed_width = page_width - redact_rect.x0 - margin
        
        # 創建插入矩形（只擴展到需要的寬度，不擴展到頁面底部）
        estimated_height = len(new_text.split('\n')) * size * 1.5
        insert_rect = fitz.Rect(
            redact_rect.x0, 
            redact_rect.y0,
            redact_rect.x0 + max_allowed_width,
            redact_rect.y0 + max(redact_rect.height, estimated_height)
        )
        
        # 檢查衝突
        conflicts = self.check_insertion_conflict(page_num, insert_rect, target_block)
        
        if conflicts:
            logger.warning(f"檢測到 {len(conflicts)} 個潛在衝突:")
            for conflict in conflicts:
                logger.warning(f"  - 文字塊: '{conflict['text'][:30]}...', 重疊比例: {conflict['overlap_ratio']:.2%}")
            
            # 調整插入矩形，避免衝突
            # 策略：縮小插入區域，或向下移動
            min_y = max(conflict['rect'].y1 for conflict in conflicts)
            if min_y > insert_rect.y0:
                insert_rect.y0 = min_y + size * 0.5  # 添加一些間距
                logger.debug(f"調整插入位置以避免衝突，新位置: {insert_rect.y0}")
        
        # --- 步驟 3: 在快照上執行編輯 ---
        success_snapshot = None
        try:
            # 克隆頁面
            temp_doc = fitz.open()
            temp_doc.insert_pdf(self.doc, from_page=page_num - 1, to_page=page_num - 1)
            temp_page = temp_doc[0]
            
            # 只清除目標文字塊的精確區域
            temp_page.add_redact_annot(redact_rect)
            temp_page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
            logger.debug(f"已清除目標區域: {redact_rect}")
            
            # --- 步驟 4: 插入新文字 ---
            # 使用 HTML 方式（支援中英文混合）
            html_content = self._convert_text_to_html(new_text, size, color)
            css = f"""
                span {{
                    font-size: {size}pt;
                    color: rgb({int(color[0]*255)}, {int(color[1]*255)}, {int(color[2]*255)});
                }}
                .helv {{ font-family: helv; }}
                .cjk {{ font-family: cjk; }}
            """
            
            # 使用調整後的插入矩形
            temp_page.insert_htmlbox(insert_rect, html_content, css=css)
            temp_page.update()
            
            # --- 步驟 5: 驗證插入結果 ---
            # 檢查插入的文字是否正確
            inserted_blocks = self.get_text_blocks_in_rect(0, insert_rect)
            if inserted_blocks:
                # 驗證插入的文字內容
                inserted_text = "".join([block['text'] for block in inserted_blocks])
                clean_inserted = "".join(inserted_text.split())
                clean_new = "".join(new_text.strip().split())
                similarity = difflib.SequenceMatcher(None, clean_inserted, clean_new).ratio()
                
                if similarity > 0.90:
                    success_snapshot = temp_doc
                    logger.debug(f"文字插入成功，相似度: {similarity:.2f}")
                else:
                    temp_doc.close()
                    raise RuntimeError(f"插入驗證失敗，相似度: {similarity:.2f}")
            else:
                temp_doc.close()
                raise RuntimeError("插入後未找到文字塊")
            
            # --- 步驟 6: 應用更改 ---
            if success_snapshot:
                self.doc.delete_page(page_num - 1)
                self.doc.insert_pdf(success_snapshot, from_page=0, to_page=0, start_at=page_num - 1)
                logger.info(f"文字編輯成功: 頁面 {page_num}")
                return True
            else:
                raise RuntimeError("未知錯誤，未能生成成功快照")
        
        except Exception as e:
            logger.error(f"文字編輯失敗: {e}")
            if success_snapshot and not success_snapshot.is_closed:
                success_snapshot.close()
            raise
        
        return False
    
    def _convert_text_to_html(self, text: str, font_size: int, color: tuple) -> str:
        """將文字轉換為 HTML（支援中英文混合）"""
        import re
        html_parts = []
        pattern = re.compile(r'([\u4e00-\u9fff\u3040-\u30ff]+|[a-zA-Z0-9]+| +|\n)')
        parts = pattern.findall(text)
        
        for part in parts:
            if part == '\n':
                html_parts.append('<br>')
            elif part.isspace():
                html_parts.append('&nbsp;' * len(part))
            elif re.match(r'[\u4e00-\u9fff\u3040-\u30ff]+', part):
                html_parts.append(f'<span class="cjk">{part}</span>')
            else:
                html_parts.append(f'<span class="helv">{part}</span>')
        
        return "".join(html_parts)


# ==================== 使用範例 ====================

def example_safe_edit():
    """使用安全編輯方法的範例"""
    doc = fitz.open("input.pdf")
    editor = ImprovedTextEditor(doc)
    
    # 編輯第一頁的文字
    # 提供原始文字可以幫助精確定位
    rect = fitz.Rect(100, 100, 400, 200)
    success = editor.edit_text_safe(
        0,  # 頁碼（0-based）
        rect,
        "這是新文字",
        font="helv",
        size=12,
        color=(0, 0, 0),
        original_text="這是舊文字"  # 可選：幫助精確定位
    )
    
    if success:
        doc.save("output_safe.pdf", garbage=0)
    
    doc.close()


if __name__ == "__main__":
    example_safe_edit()
