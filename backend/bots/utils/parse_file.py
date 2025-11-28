import os
import docx
import shutil
import PyPDF2
import logging
import tempfile
import subprocess
from pathlib import Path
from typing import Optional
from bs4 import BeautifulSoup
from PyPDF2 import PdfReader, errors as pypdf_errors

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Optional OCR support
try:
    from pdf2image import convert_from_path
    import pytesseract
    OCR_AVAILABLE = True
except Exception:
    OCR_AVAILABLE = False

# Optional RTF parser (python)
try:
    from striprtf.striprtf import rtf_to_text
    STRIPRTF_AVAILABLE = True
except Exception:
    STRIPRTF_AVAILABLE = False

# Optional ODF (odfpy)
try:
    from odf.opendocument import load as odf_load
    from odf.text import P as ODF_P
    ODFPY_AVAILABLE = True
except Exception:
    ODFPY_AVAILABLE = False


def _run_cmd(cmd: list[str]) -> Optional[str]:
    """Run external command and return decoded stdout on success, or None on failure.
    Does not raise; logs stderr for debugging.
    """
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        logger.debug("Command not found: %s", cmd[0])
        return None

    if res.returncode != 0:
        stderr = res.stderr.decode('utf-8', errors='ignore').strip()
        logger.debug("Command %s failed (rc=%s): %s", cmd, res.returncode, stderr)
        return None

    try:
        return res.stdout.decode('utf-8')
    except Exception:
        return res.stdout.decode('latin-1', errors='ignore')


def _extract_doc_with_cli(path: str) -> Optional[str]:
    """Try to extract .doc via antiword/catdoc, then fallback to libreoffice (soffice).
    Returns extracted text or None if all attempts fail.
    """
    cmds = [['antiword', path], ['catdoc', path],]
    for c in cmds:
        out = _run_cmd(c)
        if out:
            return out

    # Fallback: use libreoffice/soffice to convert to txt inside a temporary directory
    try:
        tmpdir = tempfile.mkdtemp(prefix='soffice_conv_')
        try:
            subprocess.run([
                'soffice', '--headless', '--convert-to', 'txt:Text', '--outdir', tmpdir, path
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            out_path = Path(tmpdir) / (Path(path).stem + '.txt')
            if out_path.exists():
                with out_path.open('r', encoding='utf-8', errors='ignore') as f:
                    data = f.read()
                return data
        finally:
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                logger.debug('Failed to remove tmpdir %s', tmpdir)
    except FileNotFoundError:
        logger.debug('soffice not found')
    except Exception as exc:
        logger.debug('soffice conversion error: %s', exc)

    return None


def parse_document(file_path: str) -> str:
    """Extracts text from multiple document formats.
    Supported: .pdf, .docx, .doc, .txt, .rtf, .odt, .html/.htm
    Raises FileNotFoundError if file not found or ValueError on unsupported/failed extraction.
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    ext = Path(file_path).suffix.lower()

    try:
        if ext == '.pdf':
            with open(file_path, 'rb') as f:
                try:
                    reader = PyPDF2.PdfReader(f, strict=False)
                    text_parts = []
                    for page in reader.pages:
                        try:
                            p = page.extract_text()
                        except Exception:
                            p = None
                        if p:
                            text_parts.append(p)
                    text = '\n'.join(text_parts).strip()
                except pypdf_errors.PdfReadError as e:
                    logging.warning("PyPDF2 failed to read PDF (%s). Trying pdftotext/OCR. Path=%s", e, file_path)
                    text = ""
        
            # Если PyPDF2 не дал текста - попробуем pdftotext (poppler) если доступен
            if not text:
                pdftotext_out = _run_cmd(['pdftotext', '-layout', file_path, '-'])
                if pdftotext_out:
                    return pdftotext_out
        
            # Если всё ещё пусто и OCR доступен - применяем OCR
            if not text and OCR_AVAILABLE:
                try:
                    pages = convert_from_path(file_path)
                    ocr_text_parts = []
                    for page in pages:
                        ocr_text_parts.append(pytesseract.image_to_string(page))
                    return '\n'.join(ocr_text_parts).strip()
                except Exception as e:
                    logging.exception("PDF OCR failed: %s", e)
            
            if text:
                return text
    
            raise ValueError(f"Ошибка при обработке файла {file_path}: PDF не содержит извлекаемого текста или файл повреждён.")

        elif ext == '.docx':
            doc = docx.Document(file_path)
            return '\n'.join(p.text for p in doc.paragraphs)

        elif ext == '.doc':
            doc_text = _extract_doc_with_cli(file_path)
            if doc_text:
                return doc_text
            raise ValueError('Не удалось извлечь текст из .doc (установите antiword, catdoc или libreoffice)')

        elif ext == '.txt':
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()

        elif ext == '.rtf':
            if STRIPRTF_AVAILABLE:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    rtf = f.read()
                return rtf_to_text(rtf)

            # fallback: use unrtf CLI
            out = _run_cmd(['unrtf', '--text', file_path])
            if out:
                return out
            raise ValueError('RTF: нужна библиотека striprtf или утилита unrtf')

        elif ext == '.odt':
            if ODFPY_AVAILABLE:
                doc = odf_load(file_path)
                paras = doc.getElementsByType(ODF_P)
                parts = []
                for p in paras:
                    if p.firstChild is not None:
                        try:
                            parts.append(p.firstChild.data)
                        except Exception:
                            parts.append('')
                return '\n'.join(parts)

            # fallback to libreoffice convert
            tmpdir = tempfile.mkdtemp(prefix='soffice_conv_')
            try:
                subprocess.run([
                    'soffice', '--headless', '--convert-to', 'txt:Text', '--outdir', tmpdir, file_path
                ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                out_path = Path(tmpdir) / (Path(file_path).stem + '.txt')
                if out_path.exists():
                    with out_path.open('r', encoding='utf-8', errors='ignore') as f:
                        data = f.read()
                    return data
            finally:
                try:
                    shutil.rmtree(tmpdir)
                except Exception:
                    logger.debug('Failed to remove tmpdir %s', tmpdir)

            raise ValueError('ODT: нужна odfpy или libreoffice (soffice)')

        elif ext in ('.html', '.htm'):
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as file:
                soup = BeautifulSoup(file, 'html.parser')
            return soup.get_text()

        else:
            raise ValueError(f"Неподдерживаемый формат файла: {ext}")

    except Exception as e:
        raise ValueError(f"Ошибка при обработке файла {file_path}: {str(e)}") from e