pip install -r /var/www/html/requirements.txt
#sh -c 'echo "" > $(docker inspect --format="{{.LogPath}}" parser_vin_dc_gibdd)'
python3 service.py