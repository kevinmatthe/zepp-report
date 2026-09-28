"""Verified Huami data_type=0: 1440 triples (category, intensity, steps).

Layout: Gadgetbridge FetchActivityOperation; validated against all 30 archived
step totals. Unknown encodings never invalidate the rest of a band's data.
Category/intensity remain raw codes because their current firmware units are unknown.
"""
import base64
import time


def minute_activity(row,base,total,now_ms=None,day_end=None):
    def unavailable(status,message):
        return [],[],{'status':status,'message':message}
    encoded=row.get('data')
    if not encoded:
        return unavailable('missing','上游未提供分钟活动数据')
    if type(row.get('data_type')) is not int or row['data_type']!=0:
        return unavailable('unsupported','尚未识别此分钟活动编码，日汇总仍可查看')
    try:
        raw=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError):
        return unavailable('unsupported','分钟活动编码无法解析，原始响应已保留')
    if len(raw)!=4320:
        return unavailable('unsupported','分钟活动数据长度未识别，未推算缺失分钟')
    if day_end is not None and day_end-base!=86400000:
        return unavailable('unsupported','夏令时切换日的分钟编码尚未验证，未推算时间对应关系')
    counts=raw[2::3]
    if total is None or sum(counts)!=total:
        return unavailable('inconsistent','分钟步数与日汇总无法核对，未推算分钟分布')
    cutoff=time.time()*1000 if now_ms is None else now_ms
    samples=[{'time':base+i*60000,'steps':count,'category_raw':raw[i*3],
              'intensity_raw':raw[i*3+1]} for i,count in enumerate(counts) if base+(i+1)*60000<=cutoff]
    return ([{'time':x['time'],'value':x['steps']} for x in samples],samples,
            {'status':'observed','message':'原始每分钟计步；0 表示记录为零，采集时尚未结束或未来的分钟不展示'})
