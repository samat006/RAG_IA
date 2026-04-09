import os
import json
import xml.etree.ElementTree as ET
from typing import Dict, Any, Tuple
from datetime import datetime
import fitz  # PyMuPDF

class PDFLoader:
    """
    Loader PDF pour documents juridiques.
    
    Utilise PyMuPDF (fitz) pour:
    - Extraction de texte robuste (compatible vieux PDF)
    - Détection géométrique des headers/footers
    """
    
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.metadata = {
            'source_file': os.path.basename(file_path),
            'source_type': 'pdf'
        }
        self.raw_text = ""
        self.pages_data = []
    
    def load(self) -> Dict[str, Any]:
        """
        Extraction complète du PDF avec nettoyage géométrique.
        """
        print(f"\n📄 Chargement PDF (PyMuPDF): {self.file_path}")
        
        doc = fitz.open(self.file_path)
        self.metadata['num_pages'] = len(doc)
        
        for page_num, page in enumerate(doc, start=1):
            # Dimensions
            rect = page.rect
            page_height = rect.height
            
            # Extraction des blocs de texte
            # blocks: (x0, y0, x1, y1, text, block_no, block_type)
            blocks = page.get_text("blocks")
            
            cleaned_text = self._clean_headers_footers_geometric(
                blocks, 
                page_height
            )
            
            self.pages_data.append({
                'page_num': page_num,
                'text': cleaned_text,
                'height': page_height,
                'width': rect.width
            })
            
        doc.close()
        
        # Assemblage du texte complet
        self.raw_text = "\n\n".join([p['text'] for p in self.pages_data])
        
        print(f"  ✅ {len(self.raw_text)} caractères extraits sur {self.metadata['num_pages']} pages")
        
        return {
            'raw_text': self.raw_text,
            'metadata': self.metadata,
            'pages_data': self.pages_data
        }
    
    def _clean_headers_footers_geometric(
        self, 
        blocks: list, 
        page_height: float
    ) -> str:
        """
        Suppression des headers/footers par analyse géométrique.
        """
        # Zones à exclure (en points, origine en haut à gauche)
        # On garde le contenu entre 8% et 92% de la hauteur
        header_limit = page_height * 0.08
        footer_limit = page_height * 0.92
        
        filtered_blocks = []
        for b in blocks:
            # b = (x0, y0, x1, y1, text, block_no, block_type)
            if b[6] == 0: # Type 0 = texte
                y0, y1 = b[1], b[3]
                y_center = (y0 + y1) / 2
                
                # On garde seulement les blocs dans la zone "body"
                if header_limit < y_center < footer_limit:
                    filtered_blocks.append(b[4]) # b[4] est le texte
        
        # Reconstruction du texte
        cleaned_text = '\n'.join(filtered_blocks)
        
        # Post-traitement : suppression des patterns résiduels
        noise_patterns = [
            'Doctrine',
            'www.legifrance.gouv.fr',
            'JURITEXT',
            'Identifiant Légifrance'
        ]
        
        for pattern in noise_patterns:
            if pattern in cleaned_text:
                # On supprime la ligne entière contenant ce pattern
                lines = cleaned_text.split('\n')
                lines = [l for l in lines if pattern not in l]
                cleaned_text = '\n'.join(lines)
        
        return cleaned_text


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
