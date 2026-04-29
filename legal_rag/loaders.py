import os
import re
import json
import xml.etree.ElementTree as ET
from typing import Dict, Any, Tuple, List
from collections import Counter
from datetime import datetime
import fitz  # PyMuPDF
import io


class PDFLoader:
    """
    Loader PDF multi-modes pour documents non structurés.

    Modes (pdf_mode) :
    - "markdown"   : pymupdf4llm → Markdown structuré (tables, titres) — recommandé
    - "pdfplumber" : pdfplumber, excellent pour les tableaux de prix
    - "hybrid"     : PyMuPDF mots-XY + OCR par page si besoin
    - "ocr"        : OCR Tesseract complet (PDFs scannés)
    - "pymupdf"    : PyMuPDF brut (ancien comportement)
    """

    def __init__(self, file_path: str, use_ocr: bool = False, pdf_mode: str = "markdown"):
        self.file_path = file_path
        # rétrocompatibilité : use_ocr=True → mode ocr
        self.pdf_mode = "ocr" if use_ocr else pdf_mode
        self.metadata = {
            'source_file': os.path.basename(file_path),
            'source_type': 'pdf'
        }
        self.raw_text = ""
        self.pages_data = []

    def load(self) -> Dict[str, Any]:
        mode = self.pdf_mode
        if mode == "docling":
            return self._load_with_docling()
        elif mode == "vision":
            return self._load_with_vision_llm()
        elif mode == "markdown":
            return self._load_with_pymupdf4llm()
        elif mode == "pdfplumber":
            return self._load_with_pdfplumber()
        elif mode == "hybrid":
            return self._load_hybrid()
        elif mode == "ocr":
            return self._load_with_ocr()
        else:
            return self._load_with_pymupdf()

    # ─────────────────────────────────────────────────────────────
    # MODE DOCLING (IBM) — MEILLEUR POUR BROCHURES ET LAYOUTS COMPLEXES
    # Analyse le layout par deep learning (détecte colonnes, tables, sections)
    # Prérequis : pip install docling (télécharge ~1-2GB de modèles au 1er run)
    # ─────────────────────────────────────────────────────────────
    def _load_with_docling(self) -> Dict[str, Any]:
        try:
            from docling.document_converter import DocumentConverter
        except ImportError:
            print("  ⚠️  docling non installé → fallback pdfplumber")
            return self._load_with_pdfplumber()

        print(f"\n📄 Chargement PDF (docling): {self.file_path}")
        try:
            converter = DocumentConverter()
            result = converter.convert(self.file_path)
            md_text = result.document.export_to_markdown()

            try:
                doc = fitz.open(self.file_path)
                self.metadata['num_pages'] = len(doc)
                doc.close()
            except Exception:
                pass

            # Supprimer les balises image et redistribuer les blocs de prix flottants
            import re as _re
            md_text = _re.sub(r'\n?<!-- image -->\n?', '\n', md_text)
            md_text = _re.sub(r'\n{3,}', '\n\n', md_text).strip()
            md_text = self._redistribute_floating_prices(md_text)

            self.raw_text = md_text
            print(f"  ✅ {len(self.raw_text)} caractères (docling/Markdown) extraits")
            return {'raw_text': self.raw_text, 'metadata': self.metadata, 'pages_data': self.pages_data}
        except Exception as e:
            print(f"  ⚠️  docling échoué ({e}) → fallback pdfplumber")
            return self._load_with_pdfplumber()

    def _redistribute_floating_prices(self, md_text: str) -> str:
        """
        Les PDFs brochures stockent les prix dans des boites flottantes que docling
        regroupe après la dernière section visible sur la page plutôt que d'en face de
        chaque hôtel.

        Heuristique : si une section ## contient N blocs de prix consécutifs
        ("Chbre double : … PDJ : …") mais qu'il y a N-1 sections ## précédentes sans
        prix sur la même page, on remonte les N-1 premiers blocs vers ces sections.
        """
        PRICE_PATTERN = re.compile(
            r'((?:Chbre?|Ch\.) double[^€\n]*€[^\n]*(?:\nPDJ[^\n]*)?)|(Pour \d+ pers[^€\n]*€[^\n]*(?:\nPDJ[^\n]*)?)',
            re.IGNORECASE
        )
        # Diviser par sections ##
        parts = re.split(r'(^## .+)$', md_text, flags=re.MULTILINE)
        # parts = [before_first_heading, heading1, body1, heading2, body2, ...]

        # Reconstruire les sections sous forme de liste [(heading, body)]
        sections: List[tuple] = []
        if parts[0].strip():
            sections.append(('', parts[0]))
        i = 1
        while i < len(parts) - 1:
            sections.append((parts[i], parts[i + 1]))
            i += 2

        # Trouver les sections sans prix qui précèdent une section avec beaucoup de prix
        changed = True
        while changed:
            changed = False
            for idx, (h, b) in enumerate(sections):
                price_blocks = PRICE_PATTERN.findall(b)
                if len(price_blocks) < 2:
                    continue  # Cette section a 0 ou 1 prix → ok

                # Chercher les sections précédentes sans prix (hôtels orphelins)
                orphans = []
                for j in range(idx - 1, -1, -1):
                    oh, ob = sections[j]
                    if not oh.startswith('##'):
                        break
                    if not PRICE_PATTERN.search(ob):
                        orphans.insert(0, j)
                    else:
                        break

                if not orphans:
                    continue

                # Prendre le premier bloc de prix et le déplacer vers le premier orphelin
                first_price = next((p[0] or p[1] for p in price_blocks if p[0] or p[1]), None)
                if not first_price:
                    continue

                oi = orphans[0]
                oh, ob = sections[oi]
                sections[oi] = (oh, ob.rstrip() + '\n\n' + first_price + '\n')

                # Supprimer ce bloc de la section courante
                new_body = PRICE_PATTERN.sub('', b, count=1).strip()
                sections[idx] = (h, new_body)
                changed = True
                break

        # Reconstruire le texte
        result = []
        for h, b in sections:
            if h:
                result.append(h + b)
            else:
                result.append(b)
        return '\n\n'.join(result)

    # ─────────────────────────────────────────────────────────────
    # MODE VISION (Ollama multimodal) — MEILLEUR POUR PDFs CATALOGUE
    # Lit chaque page comme un humain via un LLM vision (llava, etc.)
    # Prérequis : ollama pull llava
    # ─────────────────────────────────────────────────────────────
    def _load_with_vision_llm(self, vision_model: str = "llava") -> Dict[str, Any]:
        try:
            import ollama as _ollama
        except ImportError:
            print("  ⚠️  ollama non installé → fallback pdfplumber")
            return self._load_with_pdfplumber()

        print(f"\n📄 Chargement PDF (Vision/{vision_model}): {self.file_path}")
        try:
            doc = fitz.open(self.file_path)
        except Exception as e:
            print(f"  ⚠️  Impossible d'ouvrir le PDF ({e}) — ignoré")
            return {'raw_text': '', 'metadata': self.metadata, 'pages_data': []}

        self.metadata['num_pages'] = len(doc)
        pages_text = []

        prompt = (
            "Tu es un assistant d'extraction de documents touristiques. "
            "Extrait TOUT le texte de cette page de guide touristique. "
            "Pour chaque établissement (hôtel, restaurant, camping, etc.), "
            "groupe ses informations ensemble : nom, adresse, téléphone, email, "
            "site web, description, tarifs. "
            "Sépare chaque établissement par une ligne vide. "
            "Ne saute aucune information. Réponds en français."
        )

        for page_num, page in enumerate(doc, start=1):
            try:
                mat = fitz.Matrix(2.0, 2.0)  # 144 DPI — bon compromis qualité/vitesse
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")

                response = _ollama.chat(
                    model=vision_model,
                    messages=[{
                        'role': 'user',
                        'content': prompt,
                        'images': [img_bytes]
                    }]
                )
                text = response['message']['content'].strip()
                pages_text.append(text)
                print(f"  Page {page_num}/{len(doc)} vision ({len(text)} chars)")
            except Exception as e:
                print(f"  ⚠️  Page {page_num} vision échouée ({e}) → fallback pdfplumber page")
                pages_text.append("")

        doc.close()

        # Pages vides → refaire avec pdfplumber en fallback
        empty_count = sum(1 for t in pages_text if not t.strip())
        if empty_count == len(pages_text):
            print("  ⚠️  Aucune page extraite par vision → fallback pdfplumber complet")
            return self._load_with_pdfplumber()

        self.raw_text = "\n\n".join([t for t in pages_text if t])
        print(f"  ✅ {len(self.raw_text)} caractères extraits (vision) sur {self.metadata['num_pages']} pages")
        return {'raw_text': self.raw_text, 'metadata': self.metadata, 'pages_data': self.pages_data}

    # ─────────────────────────────────────────────────────────────
    # MODE MARKDOWN (pymupdf4llm) — RECOMMANDÉ POUR PDFs NON STRUCTURÉS
    # ─────────────────────────────────────────────────────────────
    def _load_with_pymupdf4llm(self) -> Dict[str, Any]:
        """
        Convertit le PDF en Markdown via pymupdf4llm.
        Préserve les tables, titres, listes — idéal pour les LLMs.
        """
        try:
            import pymupdf4llm
        except ImportError:
            print("  ⚠️  pymupdf4llm non installé → fallback pdfplumber")
            return self._load_with_pdfplumber()

        print(f"\n📄 Chargement PDF (Markdown/pymupdf4llm): {self.file_path}")
        try:
            md_text = pymupdf4llm.to_markdown(
                self.file_path,
                show_progress=False,
            )
            # Métadonnées via fitz pour num_pages
            try:
                doc = fitz.open(self.file_path)
                self.metadata['num_pages'] = len(doc)
                doc.close()
            except Exception:
                pass

            self.raw_text = md_text.strip()
            print(f"  ✅ {len(self.raw_text)} caractères (Markdown) extraits")
            return {'raw_text': self.raw_text, 'metadata': self.metadata, 'pages_data': self.pages_data}
        except Exception as e:
            print(f"  ⚠️  pymupdf4llm échoué ({e}) → fallback pdfplumber")
            return self._load_with_pdfplumber()

    # ─────────────────────────────────────────────────────────────
    # MODE PDFPLUMBER — BON POUR TABLEAUX DE PRIX
    # ─────────────────────────────────────────────────────────────
    def _load_with_pdfplumber(self) -> Dict[str, Any]:
        """
        Extraction via pdfplumber : interleave texte + tableaux dans l'ordre de lecture.
        Particulièrement efficace pour les PDFs avec listes de prix et formulaires.
        """
        try:
            import pdfplumber
        except ImportError:
            print("  ⚠️  pdfplumber non installé → fallback PyMuPDF")
            return self._load_with_pymupdf()

        print(f"\n📄 Chargement PDF (pdfplumber): {self.file_path}")
        try:
            pages_text = []
            with pdfplumber.open(self.file_path) as pdf:
                self.metadata['num_pages'] = len(pdf.pages)
                for page_num, page in enumerate(pdf.pages, start=1):
                    page_text = self._extract_pdfplumber_page(page)
                    if page_text.strip():
                        pages_text.append(page_text)
                    print(f"  Page {page_num}/{len(pdf.pages)} ({len(page_text)} chars)")

            self.raw_text = "\n\n".join(pages_text)
            print(f"  ✅ {len(self.raw_text)} caractères extraits (pdfplumber)")
            return {'raw_text': self.raw_text, 'metadata': self.metadata, 'pages_data': self.pages_data}
        except Exception as e:
            print(f"  ⚠️  pdfplumber échoué ({e}) → fallback PyMuPDF")
            return self._load_with_pymupdf()

    def _extract_pdfplumber_page(self, page) -> str:
        """
        Extraction pdfplumber avec détection et séparation des colonnes au niveau
        caractère — évite tout mélange inter-colonnes sur les brochures en grille.

        Algorithme :
        1. Détecter le gap horizontal le plus large dans la zone centrale → frontière
        2. Filtrer les caractères strictement par x < boundary (gauche) ou x ≥ boundary (droite)
        3. Reconstruire chaque colonne ligne par ligne (même y → même ligne)
        """
        words = page.extract_words()
        if not words:
            return ""

        page_w = float(page.width)

        # 1. Trouver le gap dominant dans 25%–75% de la largeur de page
        center_xs = sorted(
            float(w['x0']) for w in words
            if page_w * 0.25 <= float(w['x0']) <= page_w * 0.75
        )
        boundary = None
        if len(center_xs) >= 2:
            max_gap = 0.0
            best_mid = page_w / 2
            for i in range(1, len(center_xs)):
                gap = center_xs[i] - center_xs[i - 1]
                if gap > max_gap:
                    max_gap = gap
                    best_mid = (center_xs[i] + center_xs[i - 1]) / 2
            if max_gap > page_w * 0.04:
                boundary = best_mid

        if boundary is None:
            return page.extract_text(x_tolerance=3, y_tolerance=3) or ""

        # 2. Vérifier qu'il y a du contenu significatif des deux côtés
        left_side  = [w for w in words if float(w['x0']) < boundary - 5]
        right_side = [w for w in words if float(w['x0']) > boundary + 5]
        if len(left_side) < 4 or len(right_side) < 4:
            return page.extract_text(x_tolerance=3, y_tolerance=3) or ""

        # 3. Extraction colonne gauche puis droite, au niveau caractère
        left_text  = self._chars_to_text(page.chars, x_lo=0,       x_hi=boundary)
        right_text = self._chars_to_text(page.chars, x_lo=boundary, x_hi=page_w + 1)
        parts = [p for p in [left_text, right_text] if p.strip()]
        return '\n\n---\n\n'.join(parts)

    def _chars_to_text(self, chars, x_lo: float, x_hi: float) -> str:
        """Reconstitue du texte depuis les caractères pdfplumber dans une bande X."""
        col_chars = [c for c in chars if x_lo <= float(c['x0']) < x_hi]
        if not col_chars:
            return ""

        lines_by_y: Dict[float, List] = {}
        for ch in col_chars:
            y_key = round(float(ch['top']), 1)
            lines_by_y.setdefault(y_key, []).append(ch)

        lines = []
        for y_key in sorted(lines_by_y):
            row = sorted(lines_by_y[y_key], key=lambda c: float(c['x0']))
            # Reconstitution avec espaces quand le gap entre mots est significatif
            text = ""
            prev_x1 = None
            for ch in row:
                if prev_x1 is not None and float(ch['x0']) - prev_x1 > 2:
                    text += " "
                text += ch['text']
                prev_x1 = float(ch['x1'])
            if text.strip():
                lines.append(text.strip())

        return '\n'.join(lines)

    def _load_hybrid(self) -> Dict[str, Any]:
        """
        Hybride page par page :
        - Page mono-colonne  → PyMuPDF (rapide, précis)
        - Page multi-colonnes → OCR (lit dans l'ordre visuel, évite l'interleaving)
        - Page sans texte     → OCR (PDF image)
        """
        try:
            import pytesseract
            from PIL import Image
            ocr_available = True
        except ImportError:
            ocr_available = False

        print(f"\n📄 Chargement PDF (hybride PyMuPDF+OCR): {self.file_path}")
        try:
            doc = fitz.open(self.file_path)
        except Exception as e:
            print(f"  ⚠️  Impossible d'ouvrir le PDF ({e}) — ignoré")
            return {'raw_text': '', 'metadata': self.metadata, 'pages_data': []}

        self.metadata['num_pages'] = len(doc)
        all_pages_blocks = []
        for page_num, page in enumerate(doc, start=1):
            rect = page.rect
            blocks = page.get_text("blocks")
            all_pages_blocks.append({
                'page_num': page_num, 'blocks': blocks,
                'width': rect.width, 'height': rect.height,
                'page_obj': page
            })

        repetitive_lines = self._detect_repetitive_lines(all_pages_blocks)
        pages_text = []

        for page_num, page in enumerate(doc, start=1):
            # Extraction mots XY d'abord
            try:
                word_text = self._extract_page_text_by_words(page, repetitive_lines)
            except Exception as e:
                print(f"  ⚠️  Page {page_num} words-XY échoué ({e})")
                word_text = ""

            # OCR si : page vide (PDF image) OU texte très court (extraction ratée)
            use_ocr_page = ocr_available and len(word_text.strip()) < 80

            if use_ocr_page:
                try:
                    mat = fitz.Matrix(300 / 72, 300 / 72)
                    pix = page.get_pixmap(matrix=mat)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    text = pytesseract.image_to_string(img, lang="fra").strip()
                    mode = "OCR"
                except Exception as e:
                    text = word_text
                    mode = f"words-XY(ocr-fail)"
            else:
                text = word_text
                mode = "words-XY"

            pages_text.append(text)
            print(f"  Page {page_num}/{len(doc)} [{mode}] ({len(text)} chars)")

        doc.close()
        self.raw_text = "\n\n".join([t for t in pages_text if t])
        print(f"  ✅ {len(self.raw_text)} caractères extraits sur {self.metadata['num_pages']} pages")
        return {'raw_text': self.raw_text, 'metadata': self.metadata, 'pages_data': self.pages_data}

    def _load_with_ocr(self) -> Dict[str, Any]:
        """Extraction par OCR Tesseract — robuste pour PDFs image/multi-colonnes."""
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            print("  ⚠️  pytesseract/Pillow non installé — fallback PyMuPDF")
            return self._load_with_pymupdf()

        print(f"\n📄 Chargement PDF (OCR): {self.file_path}")
        try:
            # filetype="pdf" + repair=True tolère les PDFs mal formés (structure tree corrompue, etc.)
            doc = fitz.open(self.file_path, filetype="pdf")
        except Exception as e:
            print(f"  ⚠️  Impossible d'ouvrir le PDF ({e}) — ignoré")
            return {'raw_text': '', 'metadata': self.metadata, 'pages_data': []}

        self.metadata['num_pages'] = len(doc)
        pages_text = []

        for page_num, page in enumerate(doc, start=1):
            try:
                mat = fitz.Matrix(300 / 72, 300 / 72)  # 300 DPI
                pix = page.get_pixmap(matrix=mat)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(img, lang="fra")
                pages_text.append(text.strip())
                print(f"  Page {page_num}/{len(doc)} OCR ({len(text)} chars)")
            except Exception as e:
                print(f"  ⚠️  Page {page_num} ignorée ({e})")

        doc.close()
        self.raw_text = "\n\n".join([t for t in pages_text if t])
        print(f"  ✅ {len(self.raw_text)} caractères extraits (OCR) sur {self.metadata['num_pages']} pages")

        return {
            'raw_text': self.raw_text,
            'metadata': self.metadata,
            'pages_data': self.pages_data
        }

    def _load_with_pymupdf(self) -> Dict[str, Any]:
        print(f"\n📄 Chargement PDF (PyMuPDF): {self.file_path}")

        doc = fitz.open(self.file_path)
        self.metadata['num_pages'] = len(doc)

        # Passe 1 : collecter les blocs pour détecter headers/footers répétitifs
        all_pages_blocks = []
        for page_num, page in enumerate(doc, start=1):
            rect = page.rect
            blocks = page.get_text("blocks")
            all_pages_blocks.append({
                'page_num': page_num, 'blocks': blocks,
                'width': rect.width, 'height': rect.height
            })

        repetitive_lines = self._detect_repetitive_lines(all_pages_blocks)

        # Passe 2 : extraction par blocs avec séparation colonnes
        for page_data in all_pages_blocks:
            text = self._extract_page_text(
                page_data['blocks'], page_data['width'], repetitive_lines
            )
            self.pages_data.append({
                'page_num': page_data['page_num'], 'text': text,
                'height': page_data['height'], 'width': page_data['width']
            })

        doc.close()

        self.raw_text = "\n\n".join([p['text'] for p in self.pages_data if p['text'].strip()])
        print(f"  ✅ {len(self.raw_text)} caractères extraits sur {self.metadata['num_pages']} pages")

        return {
            'raw_text': self.raw_text,
            'metadata': self.metadata,
            'pages_data': self.pages_data
        }

    def _detect_repetitive_lines(self, all_pages_blocks: List[Dict]) -> set:
        """
        Détecte les lignes qui apparaissent sur au moins 30% des pages
        → ce sont de vrais headers/footers, pas du contenu.
        """
        n_pages = len(all_pages_blocks)
        if n_pages < 3:
            return set()  # Pas assez de pages pour détecter

        line_counter = Counter()
        for page_data in all_pages_blocks:
            page_lines = set()
            for b in page_data['blocks']:
                if b[6] == 0:  # bloc texte
                    for line in b[4].split('\n'):
                        clean = line.strip()
                        if clean and len(clean) > 2:
                            page_lines.add(clean)
            line_counter.update(page_lines)

        threshold = max(3, int(n_pages * 0.30))
        return {line for line, count in line_counter.items() if count >= threshold}

    def _extract_page_text(self, blocks, page_width, repetitive_lines) -> str:
        """Extraction par blocs avec séparation colonne gauche / colonne droite."""
        text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
        if not text_blocks:
            return ""

        page_center = page_width / 2
        left_count = sum(1 for b in text_blocks if b[2] < page_center * 0.85)
        right_count = sum(1 for b in text_blocks if b[0] > page_center * 1.15)
        is_multi = left_count > 1 and right_count > 1

        if is_multi:
            left_blocks  = sorted([b for b in text_blocks if (b[0]+b[2])/2 < page_center], key=lambda b: b[1])
            right_blocks = sorted([b for b in text_blocks if (b[0]+b[2])/2 >= page_center], key=lambda b: b[1])
            ordered = left_blocks + right_blocks
        else:
            ordered = sorted(text_blocks, key=lambda b: (b[1], b[0]))

        lines_out = []
        for b in ordered:
            for line in b[4].split('\n'):
                clean = line.strip()
                if not clean or clean in repetitive_lines:
                    continue
                if re.fullmatch(r'\d{1,4}', clean):
                    continue
                lines_out.append(clean)
        return '\n'.join(lines_out)

    def _extract_page_text_by_words(self, page, repetitive_lines: set) -> str:
        """
        Extraction mot par mot avec coordonnées XY (get_text("words")).
        Reconstitue l'ordre de lecture correct pour tout type de mise en page :
        mono-colonne, multi-colonnes, brochures, rapports, etc.

        Principe :
        1. Lire chaque mot avec sa position (x0, y0, x1, y1)
        2. Regrouper les mots par ligne (même Y ± tolérance)
        3. Détecter la frontière de colonne depuis la distribution des X0
        4. Trier : lignes pleine largeur → colonne gauche → colonne droite
        """
        # (x0, y0, x1, y1, "mot", block_no, line_no, word_no)
        words = page.get_text("words")
        if not words:
            return ""

        page_width = page.rect.width
        LINE_TOL = 4  # points de tolérance verticale pour regrouper une ligne

        # ── 1. Grouper les mots en lignes ─────────────────────────────────────
        words_by_y = sorted(words, key=lambda w: (w[1], w[0]))
        lines: List[List] = []
        current_line: List = []
        current_y = None

        for w in words_by_y:
            y0 = w[1]
            if current_y is None or abs(y0 - current_y) > LINE_TOL:
                if current_line:
                    lines.append(sorted(current_line, key=lambda x: x[0]))
                current_line = [w]
                current_y = y0
            else:
                current_line.append(w)
        if current_line:
            lines.append(sorted(current_line, key=lambda x: x[0]))

        # ── 2. Détecter la frontière de colonne ───────────────────────────────
        # On cherche le plus grand gap entre les X0 de début de ligne
        # dans la zone centrale (25 %–75 % de la largeur)
        zone_l = page_width * 0.25
        zone_r = page_width * 0.75
        start_xs = sorted({round(l[0][0]) for l in lines if l and zone_l <= l[0][0] <= zone_r})

        boundary = None
        max_gap = 0
        for i in range(1, len(start_xs)):
            gap = start_xs[i] - start_xs[i - 1]
            if gap > max_gap and gap > page_width * 0.06:
                max_gap = gap
                boundary = (start_xs[i] + start_xs[i - 1]) / 2

        # ── 3. Helpers ────────────────────────────────────────────────────────
        def line_to_str(line) -> str:
            return " ".join(w[4] for w in line).strip()

        def keep(text: str) -> bool:
            if not text:
                return False
            if text in repetitive_lines:
                return False
            if re.fullmatch(r'\d{1,4}', text):
                return False
            return True

        def build(line_list) -> List[str]:
            return [
                t for t in
                (line_to_str(l) for l in sorted((l for l in line_list if l), key=lambda l: l[0][1]))
                if keep(t)
            ]

        # ── 4. Reconstruire le texte ──────────────────────────────────────────
        if boundary is None:
            return "\n".join(t for t in (line_to_str(l) for l in lines) if keep(t))

        # Multi-colonnes : pour chaque ligne, couper à la frontière
        full_lines, left_lines, right_lines = [], [], []
        GAP_MIN = 15  # gap minimal en points pour confirmer deux colonnes distinctes

        for l in lines:
            # Classement par x0 (bord gauche du mot) pour éviter les mots orphelins
            left_part  = [w for w in l if w[0] < boundary]
            right_part = [w for w in l if w[0] >= boundary]

            if left_part and right_part:
                gap = right_part[0][0] - left_part[-1][2]
                if gap >= GAP_MIN:
                    left_lines.append(left_part)
                    right_lines.append(right_part)
                else:
                    full_lines.append(l)
            elif left_part:
                left_lines.append(left_part)
            elif right_part:
                right_lines.append(right_part)
            # ligne vide → ignorée

        return "\n".join(build(full_lines) + build(left_lines) + build(right_lines))


class XMLLoader:
    """
    Loader pour ordonnances et ordres XML.
    
    Gère:
    - Namespaces XML
    - Extraction sélective (métadonnées vs. contenu)
    - Transformation en texte enrichi
    """
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.tree = None
        self.root = None
        self.namespaces = {}
    
    def load(self) -> Dict[str, Any]:
        """
        Parsing XML avec extraction métadonnées + contenu.
        """
        print(f"\n📋 Chargement XML: {self.file_path}")
        
        # Parsing
        self.tree = ET.parse(self.file_path)
        self.root = self.tree.getroot()
        
        # Détection des namespaces
        self._detect_namespaces()
        
        # Extraction métadonnées
        metadata = self._extract_metadata_from_xml()
        
        # Extraction contenu textuel
        content = self._extract_content_from_xml()
        
        print(f"  ✅ {len(content)} caractères extraits")
        
        return {
            'raw_text': content,
            'metadata': metadata,
            'source_type': 'xml',
            'source_file': os.path.basename(self.file_path)
        }
    
    def _detect_namespaces(self):
        """
        Détection automatique des namespaces XML.
        """
        # ElementTree parse automatiquement {namespace}tag
        # On extrait les namespaces depuis la racine
        if self.root.tag.startswith('{'):
            ns = self.root.tag[1:].split('}')[0]
            self.namespaces['default'] = ns
    
    def _extract_metadata_from_xml(self) -> Dict[str, Any]:
        """
        Extraction des métadonnées depuis les balises XML.
        """
        metadata = {
            'source_file': os.path.basename(self.file_path),
            'source_type': 'xml'
        }
        
        # Liste des balises métadonnées communes
        metadata_tags = [
            'reference', 'Reference', 'REFERENCE',
            'juridiction', 'Juridiction', 'JURIDICTION',
            'date', 'Date', 'DATE',
            'numero', 'Numero', 'NUMERO',
            'type', 'Type', 'TYPE',
            'formation', 'Formation',
            'president', 'President',
            'dispositif', 'Dispositif'
        ]
        
        # Recherche dans tout l'arbre
        for tag in metadata_tags:
            # Recherche sans namespace
            elem = self.root.find(f".//{tag}")
            if elem is not None and elem.text:
                # On normalise le nom de la clé en lowercase
                key = tag.lower()
                metadata[key] = elem.text.strip()
        
        # Extraction des attributs de la racine (souvent informatifs)
        if self.root.attrib:
            for key, value in self.root.attrib.items():
                # On préfixe les attributs pour les distinguer
                metadata[f"attr_{key}"] = value
        
        return metadata
    
    def _extract_content_from_xml(self) -> str:
        """
        Extraction du contenu textuel pertinent.
        """
        content_parts = []
        
        def traverse(element, depth=0):
            """Parcours récursif avec enrichissement."""
            # On skip les balises "metadata" connues
            skip_tags = ['reference', 'juridiction', 'date', 'numero']
            
            tag_name = element.tag.split('}')[-1].lower()  # Enlève namespace
            
            # Si c'est une balise de contenu avec du texte
            if element.text and element.text.strip() and tag_name not in skip_tags:
                # On enrichit avec le nom de la balise (contexte)
                text = element.text.strip()
                
                # Si la balise a un nom sémantique, on l'ajoute
                if tag_name not in ['p', 'div', 'span']:
                    content_parts.append(f"[{tag_name}]: {text}")
                else:
                    content_parts.append(text)
            
            # Récursion sur les enfants
            for child in element:
                traverse(child, depth + 1)
        
        traverse(self.root)
        
        return "\n".join(content_parts)


class JSONLoader:
    """
    Loader pour métadonnées JSON.
    
    Transformation intelligente clé-valeur → texte naturel.
    """
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.data = None
    
    def load(self) -> Dict[str, Any]:
        """
        Chargement et transformation JSON.
        """
        print(f"\n📊 Chargement JSON: {self.file_path}")
        
        with open(self.file_path, 'r', encoding='utf-8') as f:
            self.data = json.load(f)
        
        # Séparation métadonnées / contenu
        metadata, content_text = self._transform_json(self.data)
        
        metadata['source_file'] = os.path.basename(self.file_path)
        metadata['source_type'] = 'json'
        
        print(f"  ✅ {len(content_text)} caractères générés")
        
        return {
            'raw_text': content_text,
            'metadata': metadata
        }
    
    def _transform_json(self, data: Dict, prefix="") -> Tuple[Dict, str]:
        """
        Transformation récursive JSON → (métadonnées, texte).
        """
        metadata = {}
        content_parts = []
        
        for key, value in data.items():
            full_key = f"{prefix}{key}" if prefix else key
            
            # 1. Types numériques/booléens → Métadonnées
            if isinstance(value, (int, float, bool)):
                metadata[full_key] = value
            
            # 2. Chaînes de caractères → Analyse
            elif isinstance(value, str):
                # Est-ce une date ISO ?
                if self._is_iso_date(value):
                    metadata[full_key] = value
                    # On l'ajoute aussi au contenu pour recherche sémantique
                    content_parts.append(
                        f"{key.replace('_', ' ').title()}: {self._format_date(value)}"
                    )
                
                # Est-ce un identifiant/code ?
                elif self._is_structured_field(key, value):
                    metadata[full_key] = value
                
                # Sinon, c'est du contenu textuel
                else:
                    content_parts.append(
                        f"{key.replace('_', ' ').title()}: {value}"
                    )
                    # On garde aussi une version shortened en métadonnée si pertinent
                    if len(value) < 100:
                        metadata[f"{full_key}_short"] = value[:100]
            
            # 3. Listes → Énumération
            elif isinstance(value, list):
                if value:
                    # On compte les éléments (métadonnée)
                    metadata[f"{full_key}_count"] = len(value)
                    
                    # On énumère les éléments (contenu)
                    items_str = ", ".join([str(v) for v in value])
                    content_parts.append(
                        f"{key.replace('_', ' ').title()}: {items_str}"
                    )
            
            # 4. Objets imbriqués → Récursion
            elif isinstance(value, dict):
                nested_meta, nested_text = self._transform_json(value, f"{full_key}.")
                metadata.update(nested_meta)
                if nested_text:
                    content_parts.append(
                        f"\n{key.replace('_', ' ').title()}:\n{nested_text}"
                    )
        
        content_text = "\n".join(content_parts)
        return metadata, content_text
    
    @staticmethod
    def _is_iso_date(value: str) -> bool:
        """Détection date ISO."""
        try:
            datetime.fromisoformat(value.replace('Z', '+00:00'))
            return True
        except:
            return False
    
    @staticmethod
    def _format_date(iso_date: str) -> str:
        """Formatage date pour texte naturel."""
        try:
            dt = datetime.fromisoformat(iso_date.replace('Z', '+00:00'))
            # Format français: 4 novembre 2025
            mois_fr = [
                '', 'janvier', 'février', 'mars', 'avril', 'mai', 'juin',
                'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'
            ]
            return f"{dt.day} {mois_fr[dt.month]} {dt.year}"
        except:
            return iso_date
    
    @staticmethod
    def _is_structured_field(key: str, value: str) -> bool:
        """Heuristique pour détecter champs structurés."""
        # Clés contenant ces mots = structuré
        if any(k in key.lower() for k in ['id', 'code', 'ref', 'numero', 'num']):
            return True
        
        # Valeur courte sans espaces = structuré
        if len(value) < 50 and ' ' not in value:
            return True
        
        return False
