import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io

PDF_PATH = "documents/test/test.png"

doc = fitz.open(PDF_PATH)
full_text = []

for page_num, page in enumerate(doc, start=1):
    # Rendre la page en image (300 DPI pour bonne qualité OCR)
    mat = fitz.Matrix(300 / 72, 300 / 72)
    pix = page.get_pixmap(matrix=mat)
    img = Image.open(io.BytesIO(pix.tobytes("png")))

    text = pytesseract.image_to_string(img, lang="fra")
    full_text.append(f"--- PAGE {page_num} ---\n{text}")
    print(f"Page {page_num}/{len(doc)} traitée ({len(text)} chars)")

doc.close()

result = "\n\n".join(full_text)
print("\n" + "="*60)
print(result[:3000])  # Afficher les 3000 premiers caractères

# Sauvegarder le résultat complet
output_path = PDF_PATH.replace(".pdf", "_ocr.txt")
with open(output_path, "w", encoding="utf-8") as f:
    f.write(result)
print(f"\n✅ Texte complet sauvegardé dans : {output_path}")
