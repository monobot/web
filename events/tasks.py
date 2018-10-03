import io
import os
import shutil
import time

import pyqrcode
from django.conf import settings
from libs.reports.core import Report
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template import loader
from django.utils import timezone
from django_rq import job
from commons.filters import as_markdown


def get_qrcode_as_svg(text, scale=8):
    img = pyqrcode.create(str(text))
    buff = io.BytesIO()
    img.svg(buff, scale=scale)
    return buff.getvalue().decode('ascii')


def get_tickets_dir():
    _dir = os.path.join(settings.BASE_DIR, 'temporal', 'tickets')
    if not os.path.isdir(_dir):
        os.makedirs(_dir)
    return _dir


def create_ticket_pdf(ticket, force=False):
    output_dir = get_tickets_dir()
    pdf_file = 'ticket-{}.pdf'.format(ticket.keycode)
    full_name = os.path.join(output_dir, pdf_file)
    if not os.path.exists(full_name) or force:
        event = ticket.article.event
        qr_code = get_qrcode_as_svg(ticket.keycode, scale=6)
        report = Report('events/ticket.j2', {
            'ticket': ticket,
            'event': event,
            'qr_code': qr_code,
        })
        report.render(http_response=False)
        shutil.move(report.template_pdf.name, full_name)
    return full_name


def create_ticket_message(ticket):
    email = ticket.customer_email
    event = ticket.article.event
    plantilla = loader.get_template('events/email/ticket_message.md')
    subject = 'Entrada para {}'.format(event.name)
    body = plantilla.render({
        'ticket': ticket,
        'article': ticket.article,
        'category': ticket.article.category,
        'event': event,
        })
    targets = [email, ]
    msg = EmailMultiAlternatives(
        subject, body,
        from_email=settings.EMAIL_HOST_USER,
        to=targets,
    )
    html_version = '<html><head></head><body>{}</body></html>'.format(
        as_markdown(body),
        )
    msg.attach_alternative(html_version, 'text/html')
    pdf_filename = create_ticket_pdf(ticket)
    with open(pdf_filename, 'rb') as f:
        msg.attach('ticket.pdf', f.read(), 'application/pdf')
    return msg


@job
def send_ticket(ticket, force=False):
    if force:
        create_ticket_pdf(ticket, force=True)
    msg = create_ticket_message(ticket)
    with get_connection() as conn:
        msg.connection = conn
        msg.send(fail_silently=False)
        ticket.send_at = timezone.now()
        ticket.save()
    time.sleep(210)  # 210 s = 3 minutes and a half (ovh limit is 3 minutes)
