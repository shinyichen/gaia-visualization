from flask import Flask, render_template, abort, request, jsonify
from model import get_cluster, get_cluster_list, types, recover_doc_online
from report import Report
from setting import name
import groundtruth as gt
import debug

app = Flask(__name__, static_folder='static')
app.jinja_env.globals.update(str=str)  # allow str function to be used in template
app.config['JSON_AS_ASCII'] = True


@app.route('/')
def hello_world():
    return render_template('index.html',
                           name=name,
                           entities=get_cluster_list(types.Entity),
                           events=get_cluster_list(types.Events))


@app.route('/js/<path>')
def static_js(path):
    return app.send_static_file('js/'+path)


@app.route('/img/<path>')
def static_img(path):
    return app.send_static_file('img/'+path)


@app.route('/css/<path>')
def static_css(path):
    return app.send_static_file('css/'+path)


@app.route('/viz/<name>')
def show_bidirection_viz(name):
    return render_template('viz.html', name=name)


@app.route('/sviz/<name>')
def show_viz(name):
    return render_template('sviz.html', name=name)


@app.route('/cluster/entities/<uri>')
@app.route('/entities/<uri>')
def show_entity_cluster(uri):
    uri = 'http://www.isi.edu/gaia/entities/' + uri
    show_image = request.args.get('image', default=True)
    show_limit = request.args.get('limit', default=100)
    return show_cluster(uri, show_image, show_limit)

@app.route('/list/<type_>')
def show_entity_cluster_list(type_):
    limit = request.args.get('limit', default=100, type=int)
    offset = request.args.get('offset', default=0, type=int)
    sortby = request.args.get('sortby', default='size')
    if type_ == 'entity':
        return render_template('list.html',
                               type_='entity',
                               limit=limit,
                               offset=offset,
                               sortby=sortby,
                               clusters=get_cluster_list(types.Entity, limit, offset, sortby))
    elif type_ == 'event':
        return render_template('list.html',
                               type_='event',
                               limit=limit,
                               offset=offset,
                               sortby=sortby,
                               clusters=get_cluster_list(types.Events, limit, offset, sortby))
    else:
        abort(404)


@app.route('/cluster/events/<uri>')
@app.route('/events/<uri>')
def show_event_cluster(uri):
    uri = 'http://www.isi.edu/gaia/events/' + uri
    show_image = request.args.get('image', default=True)
    show_limit = request.args.get('limit', default=100)
    return show_cluster(uri, show_image, show_limit)


@app.route('/cluster/AIDA/<path:uri>')
def show_columbia_cluster(uri):
    uri = 'http://www.columbia.edu/AIDA/' + uri
    show_image = request.args.get('image', default=True)
    show_limit = request.args.get('limit', default=100)
    return show_cluster(uri, show_image, show_limit)


def show_cluster(uri, show_image=True, show_limit=100):
    cluster = get_cluster(uri)
    show_image = show_image not in {False, 'False', 'false', 'no', '0'}
    show_limit = show_limit not in {False, 'False', 'false', 'no', '0'} and (
                isinstance(show_limit, int) and show_limit) or (show_limit.isdigit() and int(show_limit))
    if not cluster:
        abort(404)
    return render_template('cluster.html', cluster=cluster, show_image=show_image, show_limit=show_limit)


@app.route('/report')
def show_report():
    update = request.args.get('update', default=False, type=bool)
    report = Report(update)
    return render_template('report.html', report=report)


@app.route('/doc/<doc_id>')
def show_doc_pronoun(doc_id):
    return render_template('doc.html', doc_id=doc_id, content=recover_doc_online(doc_id))


@app.route('/cluster/entities/gt')
def show_entity_gt():
    uri = request.args.get('e', default=None)
    cluster = get_cluster(uri)
    return render_template('groundtruth.html', cluster=cluster)


@app.route('/groundtruth', methods=['GET'])
def groundtruth():
    entity_uri = request.args.get('e', default=None)
    if entity_uri:
        gt_cluster = gt.search_cluster(entity_uri)
        return jsonify(gt_cluster)
    return jsonify(gt.get_all())


@app.route('/cluster/entities/debug', methods=['GET'])
def debugger():
    cluster_uri = request.args.get('cluster')
    if cluster_uri:
        result = debug.get_debug_for_cluster(cluster_uri)
    else:
        return not_found()

    if result:
        return jsonify(result)
    else:
        return not_found()


@app.errorhandler(404)
def not_found():
    message = {
            'status': 404,
            'message': 'Not Found: ' + request.url,
    }
    resp = jsonify(message)
    resp.status_code = 404

    return resp


if __name__ == '__main__':
    # app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
    app.debug = True
    app.run(host='0.0.0.0', port=5050)
