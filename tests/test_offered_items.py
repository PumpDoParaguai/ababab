import traderie
import app as web


def test_each_received_item_keeps_its_own_traits_and_mutations():
    props=[{'id':828,'name':'Species or Slot?','type':'string','string':'Slot'},
           {'id':1,'name':'Health','type':'bool','bool':True},
           {'id':2,'name':'Corrupt','type':'bool','bool':True,'img':'https://cdn.example.com/corrupt.png'}]
    raw={'id':11,'buyer':{'id':7},'listing':{'id':9,'seller':{'id':42},'item':{'id':3,'name':'Aereis'},
         'properties':[{'id':828,'name':'Species or Slot?','type':'string','string':'Species'}]},
         'prices':[{'item_id':10,'name':'Keruku','quantity':1,'group':0,'properties':props,'item':{'id':10,'img':'https://cdn.example.com/keruku.png'}},
                   {'item_id':10,'name':'Keruku','quantity':2,'group':1,'properties':[props[0]],'variant':{'name':'Adult','img':'https://cdn.example.com/adult.png'}}]}
    o=traderie.parse_offer(raw);a,b=o.prices
    assert a['properties']['Species or Slot?']['value']=='Slot'
    assert o.properties['Species or Slot?'].value=='Species'
    assert a['properties']['Health']['value']=='True'
    assert a['properties']['Corrupt']['icon_url']=='https://cdn.example.com/corrupt.png'
    assert 'Health' not in b['properties'] and b['group']==1
    assert a['image_url']=='https://cdn.example.com/keruku.png'
    assert b['variant']=='Adult' and b['image_url'].endswith('/adult.png')
    revision=web.offer_revision(o)
    a['properties']['Health']['value']='False'
    assert web.offer_revision(o)!=revision


def test_missing_instance_attributes_never_use_catalog_definitions():
    rows=traderie.offer_prices({'prices':[{'name':'Keruku','quantity':1,'item':{'id':10,'properties':[{'name':'Health','type':'bool','bool':True}]}},None]})
    assert rows[0]['properties']=={} and rows[0]['item_id']==10


def test_offerprops_currency_and_malformed_attributes():
    rows=traderie.offer_prices({'items':[{'nmt':900000,'currency':True},
        {'name':'Keruku','quantity':1,'offerProps':[None,{'name':'Traits','type':'string','string':'Health, Weight'}]},
        {'name':'Other','quantity':1,'properties':'invalid','image_url':'javascript:alert(1)'}]})
    assert rows[0]['currency'] and rows[0]['properties']=={}
    assert rows[1]['properties']['Traits']['value']=='Health, Weight'
    assert rows[2]['image_url'] is None and rows[2]['properties']=={}
