# milpa_ai_backend/core/logic/bm25.py
# ------------------------------------------------------------
# Búsqueda léxica (BM25) priorizando Tantivy (python-tantivy),
# con fallback a Whoosh y, en último caso, a un BM25/TF-IDF en
# memoria. Este módulo corrige la compatibilidad con versiones
# de python-tantivy donde Document.add_text espera NOMBRES de
# campo (str) y no objetos Field.
#
# API pública compatible con pruebas:
#   - idx = BM25Index(index_dir="...", backend=None)
#   - idx.reset()
#   - idx.index_many(docs_ml)   # docs_ml = [{fragment_id,text/text_es,labels[],doc_id,entities[]}, ...]
#   - idx.add_documents(docs)   # docs    = [{id,text,metadata{doc_id,labels,entities}}, ...]
#   - idx.add(id, text, metadata=None)
#   - idx.index(docs)           # alias de add_documents
#   - idx.search(query, topk=100, labels_filter=None)
#
# Selección de backend:
#  - Si existe 'tantivy' -> usa tantivy salvo que BM25_BACKEND=whoosh|memory
#  - Si no hay tantivy y sí whoosh -> usa whoosh
#  - Si no hay ninguno -> memoria
#
# Notas clave:
#  - **Tantivy**: se añaden campos con add_text("nombre_de_campo", valor),
#    NUNCA con objetos Field. Esto evita TypeError en versiones donde
#    add_text requiere str.
#  - **Whoosh**: requiere paquete 'whoosh'. Si falta, cae a memoria.
#  - **Memoria**: implementación BM25 básica, suficiente para tests.
# ------------------------------------------------------------
from __future__ import annotations

from typing import List, Dict, Any, Optional, Tuple
import os
import shutil
import re
import math
from dataclasses import dataclass
from collections import Counter, defaultdict

# ---------- Detección de backends disponibles ----------
# Tantivy (python-tantivy moderno)
try:
    import tantivy  # type: ignore
except Exception:
    tantivy = None  # noqa: N816

# Whoosh
try:
    from whoosh import index as whoosh_index  # type: ignore
    from whoosh.fields import Schema as WhooshSchema, TEXT as W_TEXT, ID as W_ID, KEYWORD as W_KEYWORD  # type: ignore
    from whoosh.qparser import MultifieldParser as WhooshMultifieldParser  # type: ignore
except Exception:
    whoosh_index = None
    WhooshSchema = None  # type: ignore
    W_TEXT = None  # type: ignore
    W_ID = None  # type: ignore
    W_KEYWORD = None  # type: ignore
    WhooshMultifieldParser = None  # type: ignore


@dataclass
class _DocLite:
    fragment_id: str
    text: str
    labels: List[str]
    doc_id: str
    entities: List[Dict[str, str]]


class BM25Index:
    """
    Índice BM25 con tres posibles backends:
      - 'tantivy'  (si python-tantivy está presente y es compatible)
      - 'whoosh'   (si whoosh está presente)
      - 'memory'   (si no hay nada más; BM25 básico)

    Se puede forzar con la variable de entorno BM25_BACKEND=tantivy|whoosh|memory
    """

    def __init__(self, index_dir: str = "data/bm25_index", backend: Optional[str] = None):
        self.index_dir = index_dir
        os.makedirs(index_dir, exist_ok=True)

        forced = (backend or os.environ.get("BM25_BACKEND", "")).strip().lower()
        self.backend = "memory"  # valor por defecto seguro
        self._mem_docs: Dict[str, _DocLite] = {}
        self._mem_df: Dict[str, int] = defaultdict(int)
        self._mem_N = 0

        # ---------- Tantivy ----------
        self._tv_index = None
        self._tv_schema = None
        # Usamos SIEMPRE nombres de campos (str) para add_text:
        self._tv_field_names = {
            "fragment_id": "fragment_id",
            "text": "text",
            "labels": "labels",
            "doc_id": "doc_id",
        }

        # ---------- Whoosh ----------
        self._wh_index = None
        self._wh_schema = None

        # Selección de backend (con detección y fallback)
        if forced in {"tantivy", "whoosh", "memory"}:
            if forced == "tantivy" and self._try_init_tantivy():
                self.backend = "tantivy"
            elif forced == "whoosh" and self._try_init_whoosh():
                self.backend = "whoosh"
            else:
                self.backend = "memory"
        else:
            if self._try_init_tantivy():
                self.backend = "tantivy"
            elif self._try_init_whoosh():
                self.backend = "whoosh"
            else:
                self.backend = "memory"

    # ------------------------- Tantivy -------------------------

    def _try_init_tantivy(self) -> bool:
        """
        Devuelve True si Tantivy está disponible y se pudo crear/abrir el índice
        con la API moderna (SchemaBuilder, QueryParser, etc.).
        """
        if tantivy is None:
            return False
        if not hasattr(tantivy, "SchemaBuilder"):
            return False

        try:
            sb = tantivy.SchemaBuilder()
            # Campos textuales; almacenamos fragment_id/doc_id/labels
            # Nota: el tamaño/analizador default suele ser suficiente para BM25
            sb.add_text_field(self._tv_field_names["fragment_id"], stored=True)
            sb.add_text_field(self._tv_field_names["text"], stored=False)
            sb.add_text_field(self._tv_field_names["labels"], stored=True)
            sb.add_text_field(self._tv_field_names["doc_id"], stored=True)
            schema = sb.build()

            # Crear o abrir índice
            if not os.path.isdir(self.index_dir) or not os.listdir(self.index_dir):
                index = tantivy.Index(schema, path=self.index_dir)
            else:
                # Compatibilidad con distintas versiones de python-tantivy
                if hasattr(tantivy, "Index") and hasattr(tantivy.Index, "open"):
                    index = tantivy.Index.open(self.index_dir)  # type: ignore[attr-defined]
                else:
                    # Si no podemos abrir, recreamos limpio
                    shutil.rmtree(self.index_dir, ignore_errors=True)
                    os.makedirs(self.index_dir, exist_ok=True)
                    index = tantivy.Index(schema, path=self.index_dir)

            self._tv_schema = schema
            self._tv_index = index
            return True
        except Exception:
            self._tv_schema = None
            self._tv_index = None
            return False

    def _tv_build_query(self, query: str):
        """
        Construye una query para Tantivy, compatible con versiones donde existe
        tantivy.QueryParser(schema, fields) y con aquellas donde el Index ofrece parse_query.
        """
        if self._tv_index is None or self._tv_schema is None:
            return None
        # Intento 1: QueryParser(schema, fields)
        try:
            if hasattr(tantivy, "QueryParser"):
                qp = tantivy.QueryParser(self._tv_schema, [self._tv_field_names["text"], self._tv_field_names["labels"]])
                return qp.parse_query(query)
        except Exception:
            pass
        # Intento 2: método parse_query del index
        try:
            parse_query = getattr(self._tv_index, "parse_query", None)
            if callable(parse_query):
                return parse_query(query, [self._tv_field_names["text"], self._tv_field_names["labels"]])
        except Exception:
            pass
        return None

    # ------------------------- Whoosh --------------------------

    def _try_init_whoosh(self) -> bool:
        """
        Devuelve True si Whoosh está disponible y se pudo crear/abrir el índice.
        """
        if whoosh_index is None or WhooshSchema is None:
            return False
        try:
            schema = WhooshSchema(
                fragment_id=W_ID(stored=True, unique=True),
                text=W_TEXT(stored=True),
                labels=W_KEYWORD(stored=True, commas=True, lowercase=True),
                doc_id=W_ID(stored=True),
            )
            if not whoosh_index.exists_in(self.index_dir):
                whoosh_index.create_in(self.index_dir, schema)
            idx = whoosh_index.open_dir(self.index_dir)
            self._wh_schema = schema
            self._wh_index = idx
            return True
        except Exception:
            self._wh_schema = None
            self._wh_index = None
            return False

    # ------------------------ Utilidades -----------------------

    def reset(self) -> None:
        """
        Elimina y recrea el índice del backend seleccionado.
        """
        if self.backend == "tantivy":
            if os.path.exists(self.index_dir):
                shutil.rmtree(self.index_dir, ignore_errors=True)
            os.makedirs(self.index_dir, exist_ok=True)
            self._try_init_tantivy()

        elif self.backend == "whoosh":
            if os.path.exists(self.index_dir):
                shutil.rmtree(self.index_dir, ignore_errors=True)
            os.makedirs(self.index_dir, exist_ok=True)
            self._try_init_whoosh()

        else:
            self._mem_docs.clear()
            self._mem_df.clear()
            self._mem_N = 0

    # ------------------- API de indexación (tests) -------------------

    def add_documents(self, docs: List[Dict[str, Any]]) -> None:
        """
        API esperada por los tests:
          docs = [{ "id": str, "text": str, "metadata": { "doc_id": str, "labels": [..], "entities":[..] } }, ...]
        """
        ml_docs: List[Dict[str, Any]] = []
        for d in docs:
            rid = d.get("id", "")
            text = d.get("text", "") or ""
            md = d.get("metadata", {}) or {}
            labels = md.get("labels", []) or []
            if isinstance(labels, str):
                # permitir 'a,b,c' o 'a b c'
                labels = [x for x in re.split(r"[,\s]+", labels) if x]
            ml_docs.append({
                "fragment_id": rid,
                "text": text,
                "labels": labels,
                "doc_id": md.get("doc_id", ""),
                "entities": md.get("entities", []) or [],
            })
        self.index_many(ml_docs)

    def add(self, rid: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        API uno-a-uno esperada por los tests.
        """
        md = metadata or {}
        labels = md.get("labels", []) or []
        if isinstance(labels, str):
            labels = [x for x in re.split(r"[,\s]+", labels) if x]
        self.index_many([{
            "fragment_id": rid,
            "text": text or "",
            "labels": labels,
            "doc_id": md.get("doc_id", ""),
            "entities": md.get("entities", []) or [],
        }])

    def index(self, docs: List[Dict[str, Any]]) -> None:
        """
        Alias de add_documents(docs) por compatibilidad.
        """
        self.add_documents(docs)

    # --------------------- Indexación (motor) --------------------

    def index_many(self, docs: List[Dict[str, Any]]) -> None:
        """
        Indexa una lista de documentos en el backend activo:
          docs_ml = [
            {
              "fragment_id": str,
              "text_es" | "text": str,
              "labels": [str, ...],
              "doc_id": str,
              "entities": [{...}]   # opcional
            }, ...
          ]
        """
        if self.backend == "tantivy":
            if self._tv_index is None and not self._try_init_tantivy():
                self._index_many_memory(docs)
                return

            writer = self._tv_index.writer()

            # Construimos tantivy.Document manualmente (add_text con NOMBRE de campo)
            for d in docs:
                textval = (d.get("text_es") or d.get("text") or "")
                labels_joined = " ".join(d.get("labels", []))
                tdoc = tantivy.Document()
                # IMPORTANTE: usar SIEMPRE nombres de campo (str), NO objetos Field
                tdoc.add_text(self._tv_field_names["fragment_id"], d.get("fragment_id", ""))
                tdoc.add_text(self._tv_field_names["text"], textval)
                tdoc.add_text(self._tv_field_names["labels"], labels_joined)
                tdoc.add_text(self._tv_field_names["doc_id"], d.get("doc_id", ""))
                writer.add_document(tdoc)
            writer.commit()
            return

        if self.backend == "whoosh":
            if self._wh_index is None and not self._try_init_whoosh():
                self._index_many_memory(docs)
                return

            writer = self._wh_index.writer()
            for d in docs:
                writer.update_document(
                    fragment_id=d.get("fragment_id", ""),
                    text=(d.get("text_es") or d.get("text") or ""),
                    labels=",".join(d.get("labels", [])),
                    doc_id=d.get("doc_id", ""),
                )
            writer.commit()
            return

        # memoria
        self._index_many_memory(docs)

    def _index_many_memory(self, docs: List[Dict[str, Any]]) -> None:
        # Normalizar texto: quitar acentos para matching robusto
        try:
            from unidecode import unidecode
            normalize = lambda t: unidecode(t)
        except Exception:
            normalize = lambda t: t  # Si no hay unidecode, no normalizar
        
        token_re = re.compile(r"[A-Za-zÁÉÍÓÚáéíóúñÑ0-9]+")
        for d in docs:
            fid = d["fragment_id"]
            text = (d.get("text_es") or d.get("text") or "")
            text = normalize(text)  # Normalizar antes de tokenizar
            toks = [t.lower() for t in token_re.findall(text)]
            self._mem_docs[fid] = _DocLite(
                fragment_id=fid,
                text=text,
                labels=d.get("labels", []),
                doc_id=d.get("doc_id", ""),
                entities=d.get("entities", []),
            )
            for w in set(toks):
                self._mem_df[w] += 1
        self._mem_N = len(self._mem_docs)

    # ------------------------ Búsqueda -------------------------

    def search(
        self,
        query: str,
        topk: int = 100,
        labels_filter: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """
        Retorna una lista de hits con estructura:
          [
            {
              "fragment_id": str,
              "score": float,
              "metadata": {
                "doc_id": str,
                "labels": [str, ...],
                "entities": [...]
              }
            },
            ...
          ]
        """
        if self.backend == "tantivy":
            return self._search_tantivy(query, topk, labels_filter)

        if self.backend == "whoosh":
            return self._search_whoosh(query, topk, labels_filter)

        return self._search_memory(query, topk, labels_filter)

    # ---- Tantivy ----

    def _search_tantivy(
        self, query: str, topk: int, labels_filter: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        if self._tv_index is None and not self._try_init_tantivy():
            return []

        # Construir query compatible
        q = self._tv_build_query(query)
        if q is None:
            return []

        searcher = self._tv_index.searcher()
        try:
            top_docs = searcher.search(q, topk)
        except Exception:
            return []

        # Compatibilidad: algunas versiones exponen .hits; en otras es lista de tuplas
        hits_iter: List[Tuple[float, Any]]
        if hasattr(top_docs, "hits"):
            hits_iter = top_docs.hits  # type: ignore[assignment]
        else:
            hits_iter = top_docs  # type: ignore[assignment]

        out: List[Dict[str, Any]] = []
        for score, doc_addr in hits_iter:
            doc = searcher.doc(doc_addr)

            # fragment_id - compatibilidad tantivy-py: usar indexing en lugar de .get()
            try:
                f_id_val = doc[self._tv_field_names["fragment_id"]]
            except (KeyError, TypeError):
                # Fallback si doc es dict o tiene .get()
                f_id_val = doc.get(self._tv_field_names["fragment_id"]) if hasattr(doc, "get") else ""
            fragment_id = f_id_val[0] if isinstance(f_id_val, list) else (f_id_val or "")

            # doc_id
            try:
                d_id_val = doc[self._tv_field_names["doc_id"]]
            except (KeyError, TypeError):
                d_id_val = doc.get(self._tv_field_names["doc_id"]) if hasattr(doc, "get") else ""
            doc_id = d_id_val[0] if isinstance(d_id_val, list) else (d_id_val or "")

            # labels
            try:
                lbl = doc[self._tv_field_names["labels"]]
            except (KeyError, TypeError):
                lbl = doc.get(self._tv_field_names["labels"]) if hasattr(doc, "get") else ""
            raw_labels = lbl[0] if isinstance(lbl, list) else (lbl or "")
            labels = [l for l in str(raw_labels).split() if l]

            if labels_filter and not any(l in labels for l in labels_filter):
                continue

            out.append({
                "fragment_id": fragment_id,
                "score": float(score),
                "metadata": {
                    "doc_id": doc_id,
                    "labels": labels,
                    "entities": [],  # no almacenamos entidades en BM25
                }
            })
        return out

    # ---- Whoosh ----

    def _search_whoosh(
        self, query: str, topk: int, labels_filter: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        if self._wh_index is None and not self._try_init_whoosh():
            return []

        with self._wh_index.searcher() as s:
            parser = WhooshMultifieldParser(["text", "labels"], schema=self._wh_index.schema)
            q = parser.parse(query)
            hits = s.search(q, limit=topk)
            out: List[Dict[str, Any]] = []
            for h in hits:
                labels = (h.get("labels") or "").split(",")
                if labels_filter and not any(l in labels for l in labels_filter):
                    continue
                out.append({
                    "fragment_id": h["fragment_id"],
                    "score": float(h.score),
                    "metadata": {
                        "doc_id": h.get("doc_id"),
                        "labels": labels,
                        "entities": [],
                    }
                })
            return out

    # ---- Memoria ----

    def _search_memory(
        self, query: str, topk: int, labels_filter: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        # Normalizar query: quitar acentos igual que en indexación
        try:
            from unidecode import unidecode
            query = unidecode(query)
        except Exception:
            pass  # Si no hay unidecode, continuar sin normalizar
        
        token_re = re.compile(r"[A-Za-zÁÉÍÓÚáéíóúñÑ0-9]+")
        q_tokens = [t.lower() for t in token_re.findall(query)]
        scores = []
        # BM25 parámetros típicos
        k1 = 1.5
        b = 0.75

        # Normalizar función para consistencia
        try:
            from unidecode import unidecode
            normalize = lambda t: unidecode(t)
        except Exception:
            normalize = lambda t: t
        
        doc_lens: Dict[str, int] = {}
        avgdl = 0.0
        for fid, d in self._mem_docs.items():
            text_normalized = normalize(d.text)
            toks = [t.lower() for t in token_re.findall(text_normalized)]
            doc_lens[fid] = len(toks)
            avgdl += len(toks)
        avgdl = (avgdl / max(len(self._mem_docs), 1)) if self._mem_docs else 0.0

        for fid, d in self._mem_docs.items():
            if labels_filter and not any(l in d.labels for l in labels_filter):
                continue
            text_normalized = normalize(d.text)
            toks = [t.lower() for t in token_re.findall(text_normalized)]
            tf = Counter(toks)
            score = 0.0
            for w in q_tokens:
                df = self._mem_df.get(w, 0)
                if df == 0:
                    continue
                idf = math.log(1 + (self._mem_N - df + 0.5) / (df + 0.5))
                denom = tf[w] + k1 * (1 - b + b * (doc_lens[fid] / max(avgdl, 1.0)))
                score += idf * (tf[w] * (k1 + 1)) / max(denom, 1e-9)
            if score > 0:
                scores.append((fid, score, d))

        scores.sort(key=lambda x: x[1], reverse=True)
        out: List[Dict[str, Any]] = []
        for fid, sc, d in scores[:topk]:
            out.append({
                "fragment_id": fid,
                "score": float(sc),
                "metadata": {
                    "doc_id": d.doc_id,
                    "labels": d.labels,
                    "entities": d.entities
                }
            })
        return out
