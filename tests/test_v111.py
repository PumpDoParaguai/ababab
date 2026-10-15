import unittest
from unittest.mock import Mock
import traderie

class LatestRegression(unittest.TestCase):

    def test_offer_parses_image_url(self):
        raw={'id':23,'prices':[], 'buyer':{'id':2}, 'listing':{'id':3,'amount':1, 'seller':{'id':4},'item':{'id':5,'name':'Kindeer','image_url':'https://cdn.example.com/kindeer.png'}}}
        offer=traderie.parse_offer(raw)
        self.assertEqual(offer.image_url,'https://cdn.example.com/kindeer.png')

    def test_property_icon_keeps_public_cdn_address(self):
        prop=traderie.parse_listing_property({'id':1,'name':'Glow Tail','type':'bool','bool':True,'icon_url':'https://cdn.example.com/glow.png'})
        self.assertEqual(prop.icon_url,'https://cdn.example.com/glow.png')

if __name__=='__main__':unittest.main()
