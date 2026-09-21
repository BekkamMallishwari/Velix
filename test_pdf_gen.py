from reportlab.pdfgen import canvas

c = canvas.Canvas("TC_Request_Letter.pdf")
c.drawString(100, 750, "This is a real PDF file containing a Transfer Certificate Request Letter.")
c.save()
