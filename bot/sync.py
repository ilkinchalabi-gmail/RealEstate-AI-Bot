"""
sync.py — Google Sheets sinxronizasiyası.
SQLite-dəki yazılmamış lead-ləri Google Sheets-ə köçürür.
Bot işə düşdükcə arxa planda davamlı işləyir.
"""

import asyncio
import logging
from memory import get_unsynced_leads, mark_lead_synced
from sheets import append_lead_to_sheet
from config import SHEETS_TIMEOUT, SHEETS_RETRY_ATTEMPTS, SHEETS_RETRY_DELAY

logger = logging.getLogger(__name__)


async def _append_lead_with_retry(lead: dict, max_retries: int = SHEETS_RETRY_ATTEMPTS) -> bool:
    """Lead-i Sheets-ə yazmağa cəhd et. Timeout durumunda yenidən cəhd et."""
    for attempt in range(max_retries):
        try:
            # asyncio.wait_for ilə timeout tətbiq et
            result = await asyncio.wait_for(
                asyncio.to_thread(append_lead_to_sheet, lead),
                timeout=SHEETS_TIMEOUT
            )
            if result:
                return True
            else:
                # Lead yazılmadı ama timeout olmadı
                logger.warning(f"[Sync] Lead #{lead.get('id')} yazıla bilmədi (cəhd {attempt + 1}/{max_retries})")
                if attempt < max_retries - 1:
                    await asyncio.sleep(SHEETS_RETRY_DELAY)
                continue
                
        except asyncio.TimeoutError:
            logger.warning(
                f"[Sync] Lead #{lead.get('id')} yazma TIMEOUT ({SHEETS_TIMEOUT}s) - "
                f"cəhd {attempt + 1}/{max_retries}"
            )
            if attempt < max_retries - 1:
                logger.info(f"[Sync] {SHEETS_RETRY_DELAY} saniyə gözləyir və yenidən cəhd edəcəyim...")
                await asyncio.sleep(SHEETS_RETRY_DELAY)
            continue
            
        except Exception as e:
            logger.error(
                f"[Sync] Lead #{lead.get('id')} yazma xətası: {e} "
                f"(cəhd {attempt + 1}/{max_retries})"
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(SHEETS_RETRY_DELAY)
            continue

    # Bütün cəhdlər bitdi
    logger.error(
        f"[Sync] Lead #{lead.get('id')} yazma uğursuz - {max_retries} cəhdindən sonra "
        f"timeout/xətalar baş verdi"
    )
    return False


async def sync_leads_to_sheets(interval_seconds: int = 60):
    """Arxa planda davamlı işləyən sync taskı - timeout ilə qorunmuşdur."""
    logger.info(f"[Sync] Google Sheets sync taskı başladı (interval: {interval_seconds}s)")
    
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            leads = get_unsynced_leads()
            if leads:
                logger.info(f"[Sync] {len(leads)} lead Sheets-ə yazılır...")
                for lead in leads:
                    success = await _append_lead_with_retry(lead)
                    if success:
                        mark_lead_synced(lead["id"])
                        logger.info(
                            f"[Sync] Lead #{lead['id']} ({lead.get('ad','?')}) "
                            f"Sheets-ə yazıldı ✓"
                        )
                    else:
                        logger.error(
                            f"[Sync] Lead #{lead['id']} ({lead.get('ad','?')}) "
                            f"yazıla bilmədi - retry-lər bitdi ✗"
                        )
            else:
                logger.debug("[Sync] Yazılmamış lead tapılmadı")
                
        except Exception as e:
            logger.error(f"[Sync] Sync döngüsündə xəta: {e}")
            # Döngü davam etsin, xəta bitməsin
            continue
