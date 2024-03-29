import xlwings as xw

from . import score_reader_excel_impl


class SpreadsheetWrapper:
    """Actual spreadsheet is stored here, interfacing with Excel via xlwings"""

    def __init__(self):
        self._spreadsheet = None
        pass

    def reinit(self, log, spreadsheet_path, worksheet):
        log.debug(f"Opening spreadsheet at {spreadsheet_path}")
        self._spreadsheet = xw.Book(spreadsheet_path)
        self._worksheet = worksheet
        try:
            self._spreadsheet.activate(steal_focus=True)
        except Exception as e:
            log.debug(f"Unable to activate/focus workbook, spreadsheet: "
                      f"{self._spreadsheet}, worksheet: {self._worksheet} {e}")

    def read_cell_value(self, cell_score_data):
        # Add additional error diagnostic info in case have selected wrong worksheet
        try:
            return self._spreadsheet.sheets[self._worksheet].range(cell_score_data.cell).value
        except Exception as e:
            raise RuntimeError(
                f"Error reading cell data from worksheet. Have you checked things like "
                f"the worksheet name is correct? Original error: {e}")

    def close(self):
        pass
        # .close() actually closes the spreadsheet but not the handle to it
        # we hold in Python, so do nothing


def get_score_reader(logger):
    """Returns Excel score reader instance"""
    return score_reader_excel_impl.ScoreReaderExcel(SpreadsheetWrapper, logger)
