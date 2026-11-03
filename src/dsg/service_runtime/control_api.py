from __future__ import annotations

from flask import Flask, jsonify, request

from dsg.service_runtime import endpoints
from dsg.service_runtime.configuration import ConfigurationLocked
from dsg.service_runtime.contract import KnobValueRejected, UnknownKnob
from dsg.service_runtime.engine import ServiceEngine
from dsg.service_runtime.lifecycle import TransitionRejected


def create_control_app(engine: ServiceEngine) -> Flask:
    app = Flask("control_api")

    @app.errorhandler(KnobValueRejected)
    def knob_value_rejected(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(UnknownKnob)
    def unknown_knob(error):
        return jsonify(error=f"this service has no knob {error}"), 404

    @app.errorhandler(ConfigurationLocked)
    def configuration_locked(error):
        return jsonify(error=str(error)), 409

    @app.errorhandler(TransitionRejected)
    def transition_rejected(error):
        return jsonify(error=str(error)), 409

    @app.route(f"/{endpoints.START_PROCESSING}", methods=["PUT"])
    def start_processing():
        engine.start_processing()
        return jsonify(engine.status())

    @app.route(f"/{endpoints.START_MEASUREMENT}", methods=["PUT"])
    def start_measurement():
        engine.start_measuring()
        return jsonify(engine.status())

    @app.route(f"/{endpoints.STOP_PROCESSING}", methods=["PUT"])
    def stop_processing():
        engine.stop_processing()
        return jsonify(engine.status())

    @app.route(f"/{endpoints.CHANGE_RATE}", methods=["PUT"])
    def change_rate():
        client_id = request.args.get("client_id", endpoints.DEFAULT_CLIENT_ID)
        engine.change_client_rate(client_id, float(request.args["rps"]))
        return jsonify(engine.status())

    @app.route(f"/{endpoints.HAND_OVER}", methods=["PUT"])
    def hand_over():
        admitted = engine.admit_handed_over(
            request.args["request_id"],
            int(request.args["request_entered_at_ns"]),
            request.args["admission_phase"],
            request.args["handed_over_by"],
        )
        if not admitted:
            return jsonify(error="this service does not take requests now"), 409
        return jsonify(admitted=True)

    @app.route(f"/{endpoints.CHANGE_ANY_KNOB}", methods=["PUT"])
    def change_any_knob():
        accepted = engine.change_knob(request.args["name"], request.args["value"])
        return jsonify({request.args["name"]: accepted})

    @app.route(f"/{endpoints.KNOBS}", methods=["GET"])
    def knobs():
        return jsonify(engine.knobs())

    @app.route(f"/{endpoints.STATUS}", methods=["GET"])
    def status():
        return jsonify(engine.status())

    def add_scaling_endpoint(knob_name: str, endpoint: str) -> None:
        def scale():
            return jsonify({knob_name: engine.change_knob(knob_name, request.args[knob_name])})

        app.add_url_rule(f"/{endpoint}", endpoint, scale, methods=["PUT"])

    for knob_name, endpoint in endpoints.ELASTIC_WORKBENCH_SCALING_ENDPOINTS.items():
        add_scaling_endpoint(knob_name, endpoint)

    return app
