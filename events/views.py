import logging

import stripe
from django.shortcuts import render, redirect
from django.conf import settings
from django.http import Http404

from . import forms
from . import links
from . import operations
from . import stripe_utils
from .models import Event
from .models import Refund
from .models import Trade
from .models import WaitingList
from .tasks import send_ticket
from tickets.models import Article
from tickets.models import Ticket


logger = logging.getLogger(__name__)


def index(request):
    events = Event.objects.filter(active=True)
    num_events = events.count()
    if num_events == 0:
        return render(request, 'events/no-events.html')
    if num_events == 1:
        event = events.first()
        return redirect('events:detail_event', slug=event.slug)
    else:
        return render(request, 'events/list-events.html', {
            'events': events.all()
            })


def detail_event(request, slug):
    event = Event.objects.get(slug__iexact=slug)
    return render(request, 'events/event.html', {
        'event': event,
    })


def waiting_list(request, slug):
    event = Event.objects.get(slug__iexact=slug)
    if request.method == 'POST':
        form = forms.WaitingListForm(request.POST)
        if form.is_valid():
            wl = WaitingList(
                event=event,
                name=form.cleaned_data['name'],
                surname=form.cleaned_data['surname'],
                email=form.cleaned_data['email'],
                phone=form.cleaned_data['phone'],
                )
            wl.save()
            return redirect(links.waiting_list_accepted(event.slug))
    else:
        form = forms.WaitingListForm()
    return render(request, 'events/waiting-list.html', {
        'event': event,
        'form': form,
    })


def refund(request, slug):
    logging.error('refund(request, "{}") starts'.format(slug))
    event = Event.objects.get(slug__iexact=slug)
    logging.error('   request method is {}'.format(request.method))
    if request.method == 'POST':
        form = forms.RefundForm(event, request.POST)
        logging.error('   form.is_valid() is {}'.format(form.is_valid()))
        logging.error('   form.errors is {}'.format(form.errors))
        if form.is_valid():
            ticket = form.ticket
            rf = Refund(ticket=ticket, event=event)
            rf.save()
            return redirect(links.refund_accepted(event.slug, rf.pk))
    else:
        form = forms.RefundForm(event)
    return render(request, 'events/refund.html', {
        'event': event,
        'form': form,
    })


def refund_accepted(request, slug, pk):
    event = Event.objects.get(slug__iexact=slug)
    refund = Refund.objects.get(pk=pk)
    return render(request, 'events/refund-accepted.html', {
        'event': event,
        'refund': refund,
    })


def waiting_list_accepted(request, slug):
    event = Event.objects.get(slug__iexact=slug)
    return render(request, 'events/waiting-list-accepted.html', {
        'event': event,
    })


def stripe_payment_declined(request, charge):
    return render(request, 'events/payment-declined.html', {
        'email': settings.CONTACT_EMAIL,
        'charge_id': charge.id,
        }
    )


def stripe_payment_error(request, exception):
    msg, extra_info = stripe_utils.get_description_from_exception(exception)
    return render(request, 'events/payment-error.html', {
        'msg': msg,
        'extra_info': extra_info,
        'error': str(exception),
        'email': settings.CONTACT_EMAIL,
        }
    )


def make_stripe_payment(token, label, price_in_cents, name, surname, email):
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        customer = stripe.Customer.create(
            email=email,
            source=token,
            description='{}, {}'.format(surname, name),
        )
        charge = stripe.Charge.create(
            customer=customer.id,
            amount=price_in_cents,
            currency='EUR',
            description='{}/{}, {}'.format(label, surname, name)
        )
        return charge.paid, charge.id
    except Exception as err:
        logger.error('[{}] Error en el pago por stripe'.format(
            err.__class__.__name__
            ))
        logger.error(str(err))
        return False, err


def trade_view_success(request):
    return render(request, 'trade-success.html')


def trade_view(request, sell_code, buy_code):
    trade = Trade.load(sell_code, buy_code)
    if trade is None:
        raise Http404
    refund = trade.refund
    waiting_list = trade.waiting_list
    ticket = refund.ticket
    article = ticket.article
    event = article.event
    if request.method == 'GET':
        return render(request, 'events/trade.html', {
            'event': event,
            'article': article,
            'name': waiting_list.name,
            'surname': waiting_list.surname,
            'phone': waiting_list.phone,
            'email': waiting_list.email,
            'stripe_public_key': settings.STRIPE_PUBLIC_KEY,
            })
    else:  # POST
        email = request.POST['stripeEmail']
        name = request.POST['name']
        surname = request.POST['surname']
        token = request.POST['stripeToken']
        success, response = make_stripe_payment(
            token, event.slug, article.price_in_cents,
            name, surname, email,
            )
        if success:
            payment_id = response
            operations.execute_trade(trade, payment_id)
            return redirect(links.trade_success())
        else:
            return stripe_payment_error(request, response)


def buy_ticket(request, slug):
    logger.debug("buy_tickts starts : slug={}".format(slug))
    event = Event.objects.get(slug__iexact=slug)
    all_articles = [a for a in event.all_articles()]
    active_articles = [a for a in all_articles if a.is_active()]
    num_active_articles = len(active_articles)
    # num_active_articles = 1
    if num_active_articles == 0:
        return no_available_articles(request, event, all_articles)
    elif num_active_articles == 1:
        article = active_articles[0]
        return redirect(links.ticket_purchase(article.pk))
    else:
        return select_article(request, event, all_articles, active_articles)


def no_available_articles(request, event, all_articles):
    return render(request, "events/no-available-articles.html", {
        'event': event,
        'contact_email': settings.CONTACT_EMAIL,
        })


def select_article(request, event, all_articles, active_articles):
    return render(request, "events/select-article.html", {
        'event': event,
        'all_articles': all_articles,
        'active_articles': active_articles,
        })


def ticket_purchase(request, id_article):
    article = Article.objects.select_related('event').get(pk=id_article)
    assert article.is_active(), "Este tipo de entrada no está ya disponible."
    event = article.event
    if request.method == 'POST':
        email = request.POST['stripeEmail']
        name = request.POST['name']
        surname = request.POST['surname']
        phone = request.POST.get('phone', None)
        token = request.POST['stripeToken']
        success, response = make_stripe_payment(
            token, event.slug, article.price_in_cents,
            name, surname, email,
            )
        if success:
            payment_id = response
            ticket = Ticket(
                article=article,
                customer_name=name,
                customer_surname=surname,
                customer_email=email,
                customer_phone=phone,
                payment_id=payment_id,
            )
            ticket.save()
            send_ticket.delay(ticket)
            return redirect(links.article_bought(article.pk))
        else:
            return stripe_payment_error(request, response)
    else:
        return render(request, 'events/buy-article.html', {
            'event': event,
            'article': article,
            'stripe_public_key': settings.STRIPE_PUBLIC_KEY,
            })


def article_bought(request, id_article):
    article = Article.objects.select_related('event').get(pk=id_article)
    assert article.is_active(), "Este tipo de entrada no está ya disponible."
    event = article.event
    return render(request, 'events/article-bought.html', {
        'article': article,
        'event': event,
        'contact_email': settings.CONTACT_EMAIL,
        })


def coc(request, language='es'):
    template = 'events/coc-{}.html'.format(language)
    return render(request, template)


def privacy(request):
    event = Event.objects.all().first()
    return render(request, 'events/privacy.html', {
        'event': event,
        })


def find_tickets_by_email(event, email):
    qs = event.all_tickets().filter(customer_email=email)
    return list(qs)


def resend_ticket(request, slug):
    event = Event.objects.get(slug__iexact=slug)
    form = forms.EmailForm(request.POST or None)
    if request.method == 'POST':
        if form.is_valid():
            email = form.cleaned_data['email']
            tickets = find_tickets_by_email(event, email)
            for ticket in tickets:
                send_ticket.delay(ticket)
            return redirect('events:resend_confirmation', slug=event.slug)
    return render(request, 'events/resend-ticket.html', {
        'event': event,
        'form': form,
    })


def resend_confirmation(request, slug):
    event = Event.objects.get(slug__iexact=slug)
    return render(request, 'events/resend-confirmation.html', {
        'event': event,
        'contact_email': settings.CONTACT_EMAIL,
        })


def legal(request):
    return render(request, 'events/legal.html')
