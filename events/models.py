import os
from fpdf import FPDF

import locale
import datetime
import pytz
from PIL import Image, ImageDraw, ImageFont
from colorfield.fields import ColorField

from django.db import models
from django.conf import settings
from django.db.models import Max

from speakers.models import Speaker
from organizations.models import OrganizationRole
from schedule.models import Track
from tickets.models import Ticket
from events import links


class Event(models.Model):
    name = models.CharField(max_length=256)
    # url of the event is /events/<slug>
    slug = models.SlugField(unique=True)
    active = models.BooleanField(
        help_text='The current event is shown in the events page',
        default=False
    )
    opened_ticket_sales = models.BooleanField(default=False)
    start_date = models.DateField()
    # 50 minutes as default duration for each slot
    default_slot_duration = models.DurationField(default=50 * 60)
    short_description = models.TextField(blank=True)
    description = models.TextField(
        blank=True,
        help_text='Markdown is allowed'
    )
    cover = models.ImageField(
        upload_to='events/event/',
        blank=True
    )
    poster = models.FileField(
        upload_to='events/event/',
        blank=True
    )
    sponsorship_brochure = models.FileField(
        upload_to='events/event/',
        blank=True
    )
    hero = models.ImageField(
        upload_to='events/event/',
        blank=True
    )

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return links.event(self.slug)

    def get_full_url(self):
        return 'http://{}{}'.format(
            settings.DOMAIN,
            links.event_detail(self.slug),
            )

    def get_long_start_date(self, to_locale=settings.LC_TIME_SPANISH_LOCALE):
        locale.setlocale(locale.LC_TIME, to_locale)
        return self.start_date.strftime('%A %d de %B de %Y').capitalize()

    def speakers(self):
        speaker_ids = self.schedule.values_list('speakers').distinct()
        return Speaker.objects.filter(pk__in=speaker_ids).\
            order_by('name', 'surname')

    def venue(self):
        if not self.schedule.exists():
            return None
        return self.schedule.filter(location__isnull=False).\
            first().location.venue

    def organization_roles(self):
        org_roles_ids = self.memberships.values_list(
            'category__role').distinct()
        return OrganizationRole.objects.filter(pk__in=org_roles_ids).\
            order_by('order', 'name')

    def memberships_for_display(self):
        result = {}
        for role in self.organization_roles():
            r = {}
            for cat in role.organization_categories.order_by('order', 'name'):
                orgs = cat.organizations()
                # insert joint organizations next to its reference
                for i, org in enumerate(orgs):
                    for jorg in reversed(org.joint_organizations()):
                        orgs.insert(i + 1, jorg)
                if orgs:
                    r[cat] = orgs
            if r:
                result[role] = r
        return result

    def tracks(self):
        tracks_ids = self.schedule.values_list('track').distinct()
        return Track.objects.filter(pk__in=tracks_ids).\
            order_by('order', 'name')

    def plenary_scheduled_items(self):
        return self.schedule.filter(track__isnull=True).order_by('start')

    @property
    def start_date_as_datetime(self):
        return datetime.datetime.combine(
            self.start_date, datetime.time(0, 0, tzinfo=pytz.UTC))

    def _scheduled_items_for_display(self, start=None, end=None):
        result = {'type': 'scheduled_items', 'tracks': []}
        exist_scheduled_item = False
        for track in self.tracks():
            scheduled_items = track.schedule_in_range(start, end)
            if scheduled_items:
                exist_scheduled_item = True
            result['tracks'].append(
                {'track': track, 'scheduled_items': scheduled_items})
        if not exist_scheduled_item:
            result = None
        return result

    def schedule_for_display(self):
        result = [{'type': 'tracks', 'tracks': self.tracks()}]
        start, end = self.start_date_as_datetime, None
        for psi in list(self.plenary_scheduled_items()):
            end = psi.start
            scheduled_items = self._scheduled_items_for_display(start, end)
            if scheduled_items:
                result.append(scheduled_items)
            result.append({'type': 'plenary_scheduled_item', 'schedule': psi})
            start, end = psi.end, None

        scheduled_items = self._scheduled_items_for_display(start, end)
        if scheduled_items:
            result.append(scheduled_items)
        return result

    def all_tickets(self):
        '''Get all the tickets sold for a particular event.

            Returns a queryset of tickets, with select related
            articles preloaded.
        '''
        qs = Ticket.objects.select_related('article')
        qs = qs.filter(article__event=self)
        return qs

    def all_articles(self):
        '''Get all the articles we can sold for a particular event.

            Returns a queryset of articles, with select related
            categorias preloaded, ordered by name.
        '''
        qs = self.articles.select_related('category')
        qs = qs.order_by('category__name')
        return qs

    def next_ticket_number(self):
        '''Get the number for the next ticket within this event.'''
        data = self.all_tickets().aggregate(Max('number'))
        current_number = data.get('number__max', 0) or 0
        return current_number + 1

    def render_all_badges(self, pdf_only=False, remove_badges=True):
        """
        Render all Badges for this event as images, save them and make an unique PDF with all
        badges for printing.
        :param pdf_only: If True, it won't render the intermediate badges, only the final PDF
        with all the images in the folder.
        :param remove_badges: If True, remove the intermediate badges to keep the server clean.
        :return:
        """
        if not pdf_only:
            badge = self.badge_set.first()
            for ticket in self.all_tickets():
                badge.render(ticket)
        image_dir = os.path.join(settings.MEDIA_ROOT, f"events/{self.slug}/")
        image_list = os.listdir(image_dir)
        badges = [
            Image.open(os.path.join(image_dir, img)).convert('RGB') for img in image_list if img.split('.')[1] != 'pdf'
        ]
        if len(badges) == 0:
            return
        # Calculate the size of the page (A4) depending on image dpi
        dpi = badges[0].info['dpi']
        pdf_pages = []
        offset_top = 50
        offset_side = 10
        x = offset_side
        y = offset_top
        a4_width = int(210 // 25.4 * dpi[0])
        a4_height = int(297 // 25.4 * dpi[1])
        current = Image.new("RGB", (a4_width, a4_height), (255, 255, 255))  # PDF blank page
        pdf_pages.append(current)
        for img in badges:
            width, height = img.size
            if current is None or y + height >= a4_height:
                # Create a new PDF page and reset x, y
                if current not in pdf_pages:
                    pdf_pages.append(current)
                x = offset_side
                y = offset_top
                current = Image.new("RGB", (a4_width, a4_height), (255, 255, 255))
            current.paste(img, (x, y))
            if x + (width * 2) >= a4_width:  # No more badges in the row
                x = offset_side
                y += height
            else:
                x += width
        pdf = Image.new("RGB", (a4_width, a4_height), (255, 255, 255))
        pdf_output = os.path.join(image_dir, 'print.pdf')
        pdf.save(pdf_output, "PDF", resolution=100.0, save_all=True, quality=100, append_images=pdf_pages)
        del badges
        if remove_badges:
            for img in image_list:
                if img.split('.')[1] != 'pdf':
                    os.remove(os.path.join(image_dir, img))
        return f"{settings.MEDIA_URL}events/{self.slug}/print.pdf"


class Badge(models.Model):
    event = models.ForeignKey('events.Event', on_delete=models.CASCADE)
    base_image = models.ImageField(upload_to=f"events/badges/", blank=False)
    # Coordinates start from the top-left corner
    name_coordinates = models.CharField(
        max_length=255,
        verbose_name="Person name coordinates (eg 15,23).",
        default="0,0"
    )
    name_font_size = models.PositiveIntegerField(default=24)
    name_color = ColorField(default='#FFFFFF')
    number_coordinates = models.CharField(
        max_length=255,
        verbose_name="Ticket number coordinates",
        default="0,0"
    )
    number_font_size = models.PositiveIntegerField(default=24)
    number_color = ColorField(default='#FFFFFF')
    category_coordinates = models.CharField(
        max_length=255,
        verbose_name="Ticket category coordinates",
        default="0,0"
    )
    category_font_size = models.PositiveIntegerField(default=24)
    category_color = ColorField(default='#FFFFFF')

    def __str__(self):
        return f'Badge for {self.event.name}'

    @staticmethod
    def coord_to_tuple(coord):
        return tuple(int(i) for i in coord.split(","))

    @staticmethod
    def _parse_name(name: str, surname: str):
        name_list = name.split()
        if len(name_list) >= 2 and len(name_list[1]) > 2:
            name = f"{name_list[0]} {name_list[1][:1]}."

        return f"{name} \n{surname}"

    @staticmethod
    def _hex_to_rgb(color: str)-> tuple:
        return tuple(int(color.lstrip("#")[i: i + 2], 16) for i in (0, 2, 4))

    def add_field(self, image_draw: ImageDraw, text: str, coord: str, font_size: int, color: str):
        font = ImageFont.truetype("fonts/arial.ttf", size=font_size)
        image_draw.text(
            self.coord_to_tuple(coord),
            text,
            fill=self._hex_to_rgb(color),
            font=font
        )
        return image_draw

    def render(self, ticket: Ticket):
        img = Image.open(self.base_image.path)
        image_draw = ImageDraw.Draw(img)
        self.add_field(
            image_draw,
            self._parse_name(ticket.customer_name, ticket.customer_surname),
            self.name_coordinates,
            self.name_font_size,
            self.name_color
        )
        self.add_field(
            image_draw,
            str(ticket.number),
            self.number_coordinates,
            self.number_font_size,
            self.number_color
        )
        self.add_field(
            image_draw,
            ticket.article.category.name,
            self.category_coordinates,
            self.category_font_size,
            self.category_color
        )
        # test
        path = f"{settings.MEDIA_ROOT}/events/{self.event.slug}/badge_{ticket.number}.png"
        if not os.path.exists(os.path.dirname(path)):
            try:
                os.makedirs(os.path.dirname(path))
            except OSError:
                raise
        img.save(path, quality=100)
        return img
