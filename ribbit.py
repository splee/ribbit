"""Parses Ingress destruction emails.  Edit the file directly to input your
username and password below. (config file/command line switches are on the
wishlist).

USAGE:
    python ribbit.py > /path/to/data.csv

Outputs data with columns as follows:

    Entity Owner (String) - an agent name.
    Entity Destroyer (String) - an agent name.
    Entity Type (String) - resonator, mod, link.
    Date/Time of email (DateTime) - Format: YYYY-MM-DD HH:MM:SS
    Longitude (Float) - the longitude of the portal.
    Latitude (Float) - the latitude of the portal.
"""
###############
##
## EDIT CREDENTIALS BELOW
##
###############
USERNAME = 'yourgmailaddress@gmail.example.com'
PASSWORD = 'This should really be a command line option...'

##########
# Code below, don't edit unless you like to tinker.
##########
from urlparse import urlparse, parse_qs
from bs4 import BeautifulSoup
from bs4.element import NavigableString
from email.parser import Parser
from email import utils
import datetime
import imaplib
import quopri
import time
import csv
import sys
import re

DETAIL_RE = re.compile(r'(\d) (.*) were destroyed by (.*) at (.*):(.*) hrs. - ')
LINK_RE = re.compile(r'Your Link has been destroyed by (.*) at (.*):(.*) hrs. - ')
OUTPUT_FIELDS = ['owner', 'destroyer', 'type', 'time', 'lat', 'lng']


def cast_link_coordinate(coord_str):
    """Convert a co-ordinate from an Ingress location URL to a float for use
    with standard geo-location.

    Args:
        coord_str (str): String longitude or latitude from an Ingress URL.

    Returns (float): The converted co-ordinate.
    """
    # The coordinates have their decimal place removed, but always have 6
    # decimal places.
    int_part = coord_str[:-6]
    dec_part = coord_str[-6:]
    return float('{0}.{1}'.format(int_part, dec_part))


def extract_coordinates(url):
    """Extract the latitude/longitude from an Ingress notification URL.

    Args:
        url (str): The URL for a location on the Ingress Intel Map.
    """
    query = parse_qs(urlparse(url).query)

    try:
        lat = cast_link_coordinate(query['latE6'][0])
        lng = cast_link_coordinate(query['lngE6'][0])
    except KeyError:
        # this is one of the new emails
        loc_str = query['ll']
        lat, lng = loc_str[0].split(',')
        lat = float(lat)
        lng = float(lng)

    return (lat, lng)


def get_destruction_details(raw_html, email_date):
    """Retrieves the type and count of entity destroyed, the destroyer, and
    the time of destruction.

    Args:
        raw_html (str): The HTML content of a destruction email.
        email_date (datetime): When the email containing the HTML was sent.
    """
    # decode the email's html
    soup = BeautifulSoup(raw_html)
    # contains 'elements' within the email.  This is any information about
    # destroyed entities, the agent who destroyed the entities, etc.
    elements = []

    # process the next HTML element as part of the current entity.
    capture_next = False
    # the current entity.
    current = None
    first = True
    for tag in soup:
        if first:
            owner = unicode(tag)[:-1]
            first = False
            continue

        if capture_next:
            lat, lng = extract_coordinates(tag.get('href'))
            current['lat'] = lat
            current['lng'] = lng
            elements.append(current)
            current = None
            capture_next = False
            continue

        if isinstance(tag, NavigableString):
            # this gives us the type of destruction and the player doing the
            # destruction.
            element_txt = unicode(tag)
            if 'destroyed by' in element_txt:
                if 'Link' in element_txt:
                    match = LINK_RE.match(element_txt)
                    groups = match.groups()

                    count = 1
                    entity_type = 'link'
                    player = groups[0]
                    t = datetime.datetime(email_date.year, email_date.month,
                                          email_date.day, int(groups[1]),
                                          int(groups[2]))

                else:
                    # parse the string
                    match = DETAIL_RE.match(element_txt)
                    if match is None:
                        print "Unknown destruction message: {0}".format(element_txt)
                        continue
                    groups = match.groups()

                    # convert types etc
                    count = int(groups[0])
                    entity_type = groups[1].replace('(s)', '').lower()
                    player = groups[2]

                    t = datetime.datetime(email_date.year, email_date.month,
                                          email_date.day, int(groups[3]),
                                          int(groups[4]))

                current = {'count': count,
                           'type': entity_type,
                           'owner': owner,
                           'destroyer': player,
                           'time': t,
                           'lat': None,
                           'lng': None}
                capture_next = True
    return elements


def extract_email_content(raw_content):
    """Extract the HTML content, date/time of the email, and subject from
    the raw content of the email.

    Args:
        raw_content (str): The raw, unparsed email content.
    """
    email = Parser().parsestr(raw_content)

    html_part = email.get_payload()[1]
    html_body = quopri.decodestring(html_part.get_payload())

    datetime_tuple = utils.parsedate(email['Date'])
    ts = time.mktime(datetime_tuple)
    email_datetime = datetime.datetime.fromtimestamp(ts)

    return {'html': html_body, 'date': email_datetime.date(),
            'subject': email['Subject']}


class IngressInbox(object):
    """Wraps Python's imaplib to retrieve only ingress related emails from
    GMail.

    Args:
        username (str): The username for the inbox.
        password (str): The password for the inbox.
    """

    def __init__(self, username, password):
        """Initialize the class."""

        self.mail = imaplib.IMAP4_SSL('imap.gmail.com')
        self.mail.login(username, password)
        self.mail.select()

    def search(self, get_seen=False):
        """Retrieves unread Ingress emails from the configured inbox. If
        `get_seen` is True, retrieves all Ingress emails.

        Args:
            get_seen (bool): If False, only unread message IDs are retrieved.
        """
        search_params = ['(FROM "ingress-support@google.com")']
        if not get_seen:
            search_params.append('(UNSEEN)')

        typ, data = self.mail.search(None, " ".join(search_params))
        ids = data[0]
        return ids.split()

    def fetch(self, mail_id):
        result, data = self.mail.fetch(mail_id, "(RFC822)")
        return data[0][1]


def email_notifications(username, password, get_seen=False, count=None):
    """Retrieves email notifications from GMail for ingress.

    Kwargs:
        get_seen (bool): Get both read and unread messages. Default: False
        count (int): Get N most recent messages.  If None, get all messages.
            default: None
    """
    mail = IngressInbox(username, password)
    id_list = mail.search(get_seen)
    print "Found {0} emails...".format(len(id_list))

    for i in id_list:
        yield mail.fetch(i)


def point_inside_polygon(x, y, poly):
    """Determine if a point is inside a given polygon or not.

    This was originally written as a potential way to trigger alerts if a
    destroyed entity from an email was within a given polygon (say, an
    Enlightened farm).  This idea never really made it to the light of day.

    Args:
        x (float): x co-ordinate
        y (float): y co-ordinate
        poly (list): A list of (x, y) pairs as the vertices of a polygon.
    """
    vertex_count = len(poly)
    inside = False

    p1x, p1y = poly[0]
    for i in range(vertex_count + 1):
        p2x, p2y = poly[i % vertex_count]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside

if __name__ == '__main__':
    get_seen = False
    all_details = []
    output = csv.DictWriter(sys.stdout, fields=OUTPUT_FIELDS)
    for raw_email in email_notifications(USERNAME, PASSWORD, get_seen):

        email_content = extract_email_content(raw_email)
        entities = get_destruction_details(email_content['html'],
                                           email_content['date'])
        for entity in entities:
            output.writerow(entity)
