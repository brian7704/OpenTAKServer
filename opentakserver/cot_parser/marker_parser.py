import traceback

from sqlalchemy import exc, update

from opentakserver.functions import *
from opentakserver.models.Icon import Icon
from opentakserver.models.Marker import Marker


def parse_marker(event, uid, point_pk, cot_pk, context, db, logger, socketio):
    if ((re.match("^a-[f|h|u|p|a|n|s|j|k]-[Z|P|A|G|S|U|F]", event.attrs['type']) or
         # Spot map
         re.match("^b-m-p", event.attrs['type'])) and
            # Don't worry about EUD location updates
            not event.find('takv') and
            # Ignore video streams from sources like OpenTAK ICU
            event.attrs['type'] != 'b-m-p-s-p-loc'):

        try:
            marker = Marker()
            marker.uid = event.attrs['uid']
            marker.affiliation = get_affiliation(event.attrs['type'])
            marker.battle_dimension = get_battle_dimension(event.attrs['type'])
            marker.mil_std_2525c = cot_type_to_2525c(event.attrs['type'])

            detail = event.find('detail')
            icon = None

            if detail:
                for tag in detail.find_all():
                    if 'readiness' in tag.attrs:
                        marker.readiness = tag.attrs['readiness'] == "true"
                    if 'argb' in tag.attrs:
                        marker.argb = tag.attrs['argb']
                        marker.color_hex = marker.color_to_hex()
                    if 'callsign' in tag.attrs:
                        marker.callsign = tag.attrs['callsign']
                    if 'iconsetpath' in tag.attrs:
                        marker.iconset_path = tag.attrs['iconsetpath']
                        if marker.iconset_path.lower().endswith('.png'):
                            with context:
                                filename = marker.iconset_path.split("/")[-1]

                                try:
                                    icon = db.session.execute(
                                        db.session.query(Icon).filter(Icon.filename == filename)).first()[0]
                                    marker.icon_id = icon.id
                                except:
                                    icon = db.session.execute(db.session.query(Icon).filter(
                                        Icon.filename == 'marker-icon.png')).first()
                                    if icon is None:
                                        marker.icon_id = None
                                    else:
                                        marker.icon_id = icon.id
                        elif not marker.mil_std_2525c:
                            with context:
                                icon = db.session.execute(db.session.query(Icon)
                                                               .filter(Icon.filename == 'marker-icon.png')).first()[
                                    0]
                                marker.icon_id = icon.id

                    if 'altsrc' in tag.attrs:
                        marker.location_source = tag.attrs['altsrc']

            link = event.find('link')
            if link:
                marker.parent_callsign = link.attrs['parent_callsign'] if 'parent_callsign' in link.attrs else None
                marker.production_time = link.attrs[
                    'production_time'] if 'production_time' in link.attrs else iso8601_string_from_datetime(
                    datetime.now())
                marker.relation = link.attrs['relation'] if 'relation' in link.attrs else None
                marker.relation_type = link.attrs['relation_type'] if 'relation_type' in link.attrs else None
                marker.parent_uid = link.attrs['uid'] if 'uid' in link.attrs else None
            else:
                marker.production_time = iso8601_string_from_datetime(datetime.now())

            marker.point_id = point_pk
            marker.cot_id = cot_pk

            with context:
                try:
                    db.session.add(marker)
                    db.session.commit()
                    logger.debug('added marker')
                except exc.IntegrityError:
                    db.session.rollback()
                    db.session.execute(
                        update(Marker).where(Marker.uid == marker.uid).values(point_id=marker.point_id,
                                                                              icon_id=marker.icon_id,
                                                                              **marker.serialize()))
                    db.session.commit()
                    logger.debug('updated marker')
                    marker = db.session.execute(db.session.query(Marker)
                                                     .filter(Marker.uid == marker.uid)).first()[0]

                socketio.emit('marker', marker.to_json(), namespace='/socket.io')

        except BaseException as e:
            logger.error("Failed to parse marker: {}".format(e))
            logger.debug(traceback.format_exc())
