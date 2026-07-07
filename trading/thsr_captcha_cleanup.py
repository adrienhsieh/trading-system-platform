"""
trading/thsr_captcha_cleanup.py — 驗證碼圖片清晰化（僅供人眼辨識使用）

高鐵訂票頁面的驗證碼圖片本身混雜雜訊與一條干擾曲線，肉眼不容易看清楚。
這個模組單純把圖片「去噪 + 去除干擾曲線」，回傳一張黑白分明、方便使用者
自己讀取後手動輸入的乾淨圖片 —— 完全不做文字辨識／自動解碼，
驗證碼最終還是由使用者本人看圖手動輸入。

演算法沿用使用者提供的 pre_process.py 概念（多項式回歸描繪干擾曲線後，
在該位置做局部反相以抹除曲線），只是把輸入來源從「檔案路徑」
改為「記憶體中的圖片位元組」，以配合網頁版即時抓取驗證碼圖片的流程。
"""
import io

import cv2
import numpy as np
from PIL import Image
from sklearn.preprocessing import PolynomialFeatures
from sklearn.linear_model import LinearRegression


def clean_captcha_image(raw_bytes: bytes, remove_curve: bool = True) -> bytes:
    """
    去噪並（可選）移除干擾曲線，回傳清理後的 PNG 圖片位元組。

    Args:
        raw_bytes: 原始驗證碼圖片位元組（例如直接從 THSR 官網抓下來的 response.content）。
        remove_curve: 是否嘗試移除橫貫圖片的干擾曲線。

    Returns:
        bytes: 清理後的 PNG 圖片位元組，供前端直接顯示給使用者看。
    """
    arr = np.frombuffer(raw_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        # 無法解碼時，原圖直接回傳，讓使用者至少看得到原始圖片
        return raw_bytes

    h, w, _ = img.shape
    dst = cv2.fastNlMeansDenoisingColored(img, None, 30, 30, 7, 21)
    _, thresh = cv2.threshold(dst, 127, 255, cv2.THRESH_BINARY_INV)
    imgarr = cv2.cvtColor(thresh, cv2.COLOR_BGR2GRAY)

    if not remove_curve:
        result = Image.fromarray(255 - imgarr)  # 反相回「白底黑字」，方便閱讀
        return _to_png_bytes(result)

    try:
        result_arr = _remove_curve(imgarr, thresh, w)
        result = Image.fromarray(255 - result_arr)
    except Exception:
        # 曲線移除失敗（例如圖片樣式跟預期不同）時，退回僅去噪的版本，不讓整個功能掛掉
        result = Image.fromarray(255 - imgarr)

    return _to_png_bytes(result)


def _remove_curve(imgarr: np.ndarray, thresh: np.ndarray, w: int) -> np.ndarray:
    """以二次多項式回歸描繪干擾曲線的軌跡，並在該軌跡位置做局部反相以抹除曲線。"""
    work = imgarr.copy()
    work[:, 5:w - 5] = 0
    ys, xs = np.where(work == 255)
    if len(xs) < 10:
        raise ValueError("偵測到的曲線像素過少，可能沒有干擾曲線")

    X = np.array([xs])
    Y = 47 - ys

    poly_reg = PolynomialFeatures(degree=2)
    X_ = poly_reg.fit_transform(X.T)
    regr = LinearRegression()
    regr.fit(X_, Y)

    X2 = np.array([[i for i in range(0, w)]])
    X2_ = poly_reg.fit_transform(X2.T)

    newimg = cv2.cvtColor(thresh, cv2.COLOR_BGR2GRAY)
    for ele in np.column_stack([regr.predict(X2_).round(0), X2[0]]):
        pos = 47 - int(ele[0])
        col = int(ele[1])
        if 0 <= pos - 2 and pos + 4 <= newimg.shape[0]:
            newimg[pos - 2:pos + 4, col] = 255 - newimg[pos - 2:pos + 4, col]
    return newimg


def _to_png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
