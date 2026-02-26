import sys
from PySide6.QtWidgets import QApplication
from model.pdf_model import PDFModel
from view.pdf_view import PDFView
from controller.pdf_controller import PDFController

if __name__ == "__main__":
    app = QApplication(sys.argv)
    model = PDFModel()
    view = PDFView()
    controller = PDFController(model, view)
    view.controller = controller
    view.show()
    if len(sys.argv) > 1:
        controller.open_pdf(sys.argv[1])
    sys.exit(app.exec())