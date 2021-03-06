from billy.scrape import NoDataForPeriod
from billy.scrape.bills import BillScraper, Bill
from billy.scrape.votes import Vote
from tn import metadata
import datetime
import lxml.html
import re

_categorizers = (
    ('Amendment adopted', 'amendment:passed'),
    ('Amendment failed', 'amendment:failed'),
    ('Amendment proposed', 'amendment:introduced'),
    ('Divided committee report', 'committee:passed'),
    ('Filed for intro.', ['bill:introduced', 'bill:reading:1']),
    ('Reported back amended, do not pass', 'committee:passed:unfavorable'),
    ('Reported back amended, do pass', 'committee:passed:favorable'),
    ('Reported back amended, without recommendation', 'committee:passed'),
    ('Reported back, do not pass', 'committee:passed:unfavorable'),
    ('w/ recommend', 'committee:passed:favorable'),
    ('Ref. to', 'committee:referred'),
    ('Recieved from House', 'bill:introduced'),
    ('Recieved from Senate', 'bill:introduced'),
    ('Second reading, adopted', ['bill:passed', 'bill:reading:2']),
    ('Second reading, failed', ['bill:failed', 'bill:reading:2']),
    ('Second reading, passed', ['bill:passed', 'bill:reading:2']),
    ('Transmitted to Gov. for action.', 'governor:received'),
    ('Signed by Governor, but item veto', 'governor:vetoed:line-item'),
    ('Signed by Governor', 'governor:signed'),
    ('Withdrawn', 'bill:withdrawn'),
)

def categorize_action(action):
    for prefix, types in _categorizers:
        #if action.startswith(prefix):
        if prefix in action:
            return types
    return 'other'

class TNBillScraper(BillScraper):
    state = 'tn'

    def scrape(self, chamber, term):

        if chamber == 'lower':
            raise ValueError('TN can only be run with chamber=upper')

        #types of bills
        abbrs = ['HB', 'HJR', 'HR', 'SB','SJR', 'SR']

        for abbr in abbrs:

            if 'B' in abbr:
                bill_type = 'bill'
            elif 'JR' in abbr:
                bill_type = 'joint resolution'
            else:
                bill_type = 'resolution'

            #Checks if current term
            if term == self.metadata["terms"][-1]["sessions"][0]:
                bill_listing = 'http://wapp.capitol.tn.gov/apps/indexes/BillIndex.aspx?StartNum=%s0001&EndNum=%s9999' % (abbr, abbr)
            else:
                bill_listing = 'http://wapp.capitol.tn.gov/apps/archives/BillIndex.aspx?StartNum=%s0001&EndNum=%s9999&Year=%s' % (abbr, abbr, term)

            with self.urlopen(bill_listing) as bill_list_page:
                bill_list_page = lxml.html.fromstring(bill_list_page)
                for bill_links in bill_list_page.xpath('////div[@id="open"]//a'):
                    bill_link = bill_links.attrib['href']
                    if '..' in bill_link:
                        bill_link = 'http://wapp.capitol.tn.gov/apps' + bill_link[2:len(bill_link)]
                    self.scrape_bill(term, bill_link, bill_type)

    def scrape_bill(self, term, bill_url, bill_type):

        with self.urlopen(bill_url) as page:
            page = lxml.html.fromstring(page)
            matching_bill = False
            chamber1 = page.xpath('//span[@id="lblBillSponsor"]/a[1]')[0].text

            #Checking if there is a matching bill
            if len(page.xpath('//span[@id="lblCoBillSponsor"]/a[1]')) > 0:
                matching_bill = True

                chamber2 = page.xpath('//span[@id="lblCoBillSponsor"]/a[1]')[0].text

                if '*' in chamber1:
                    bill_id = chamber1.replace(' ', '')[1:len(chamber1)]
                    secondary_bill_id = chamber2.replace(' ', '')
                else:
                    bill_id = chamber2.replace(' ', '')[1:len(chamber2)]
                    secondary_bill_id = chamber1.replace(' ', '')

                primary_chamber = 'lower' if 'H' in bill_id else 'upper'

            else:
                primary_chamber = 'lower' if 'H' in chamber1 else 'upper'
                bill_id = chamber1.replace(' ', '')[1:len(chamber1)]
                secondary_bill_id = None

            title = page.xpath("//span[@id='lblAbstract']")[0].text

            #Bill subject
            subject_pos = title.find('-')
            subject = title[0:subject_pos - 1]

            bill = Bill(term, primary_chamber, bill_id, title, type=bill_type,
                        secondary_bill_id=secondary_bill_id, subject=subject)
            bill.add_source(bill_url)

            # Primary Sponsor
            sponsor = page.xpath("//span[@id='lblBillSponsor']")[0].text_content().split("by")[-1]
            sponsor = sponsor.replace('*','').strip()
            bill.add_sponsor('primary',sponsor)

            # Co-sponsors unavailable for scraping (loaded into page via AJAX)

            # Full summary doc
            summary = page.xpath("//span[@id='lblBillSponsor']/a")[0]
            bill.add_document('Full summary', summary.get('href'))

            #Primary Actions
            tables = page.xpath("//table[@id='tabHistoryAmendments_tabHistory_gvBillActionHistory']")
            actions_table = tables[0]
            action_rows = actions_table.xpath("tr[position()>1]")
            for ar in action_rows:
                action_taken = ar.xpath("td")[0].text
                action_date = datetime.datetime.strptime(ar.xpath("td")[1].text.strip(), '%m/%d/%Y')
                action_type = categorize_action(action_taken)
                bill.add_action(primary_chamber, action_taken, action_date, action_type)

            #Primary Votes
            votes_link = page.xpath("//span[@id='lblBillVotes']/a")
            if(len(votes_link) > 0):
                votes_link = votes_link[0].get('href')
                bill = self.scrape_votes(bill, sponsor, 'http://wapp.capitol.tn.gov/apps/Billinfo/%s' % (votes_link,))

            #If there is a matching bill
            if matching_bill == True:

                #Secondary Sponsor
                secondary_sponsor = page.xpath("//span[@id='lblCoBillSponsor']")[0].text_content().split("by")[-1]
                secondary_sponsor = secondary_sponsor.replace('*','').strip()
                bill.add_sponsor('secondary', secondary_sponsor)

                #Secondary Actions
                tables2 = page.xpath("//table[@id='tabHistoryAmendments_tabHistory_gvCoActionHistory']")
                actions2_table = tables2[0]
                action2_rows = actions2_table.xpath("tr[position()>1]")
                for ar2 in action2_rows:
                    action2_taken = ar2.xpath("td")[0].text
                    action2_date = datetime.datetime.strptime(ar2.xpath("td")[1].text.strip(), '%m/%d/%Y')
                    action2_type = categorize_action(action2_taken)
                    bill.add_action(chamber2, action2_taken, action2_date, action2_type)

                #Secondary Votes
                votes2_link = page.xpath("//span[@id='lblBillVotes']/a")
                if(len(votes_link) > 0):
                    votes2_link = votes2_link[0].get('href')
                    bill = self.scrape_votes(bill, secondary_sponsor, 'http://wapp.capitol.tn.gov/apps/Billinfo/%s' % (votes_link,))

            self.save_bill(bill)


    def scrape_votes(self, bill, sponsor, link):
        with self.urlopen(link) as page:
            page = lxml.html.fromstring(page)
            raw_vote_data = page.xpath("//span[@id='lblVoteData']")[0].text_content()
            raw_vote_data = raw_vote_data.strip().split('%s by %s - ' % (bill['bill_id'], sponsor))[1:]
            for raw_vote in raw_vote_data:
                raw_vote = raw_vote.split(u'\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0\xa0')
                motion = raw_vote[0]

                vote_date = re.search('(\d+/\d+/\d+)', motion)
                if vote_date:
                    vote_date = datetime.datetime.strptime(vote_date.group(), '%m/%d/%Y')

                passed = ('Passed' in motion) or ('Adopted' in raw_vote[1])
                vote_regex = re.compile('\d+$')
                aye_regex = re.compile('^.+voting aye were: (.+) -')
                no_regex = re.compile('^.+voting no were: (.+) -')
                yes_count = None
                no_count = None
                other_count = 0
                ayes = []
                nos = []

                for v in raw_vote[1:]:
                    if v.startswith('Ayes...') and vote_regex.search(v):
                        yes_count = int(vote_regex.search(v).group())
                    elif v.startswith('Noes...') and vote_regex.search(v):
                        no_count = int(vote_regex.search(v).group())
                    elif aye_regex.search(v):
                        ayes = aye_regex.search(v).groups()[0].split(', ')
                    elif no_regex.search(v):
                        nos = no_regex.search(v).groups()[0].split(', ')

                if yes_count and no_count:
                    passed = yes_count > no_count
                else:
                    yes_count = no_count = 0


                vote = Vote(bill['chamber'], vote_date, motion, passed, yes_count, no_count, other_count)
                vote.add_source(link)
                for a in ayes:
                    vote.yes(a)
                for n in nos:
                    vote.no(n)
                bill.add_vote(vote)

        return bill
