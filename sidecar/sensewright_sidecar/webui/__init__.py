"""Built-in browser panel for the Sensewright sidecar.

A tiny, dependency-free single-page app served at ``/`` that runs *alongside*
The Sims 4 in any browser on the same machine. It shows the live sidecar state
and edits the same ``ControlSpec`` registry the in-game panel uses, driving the
public ``/v1/*`` API. See ``router.py`` for the security model.
"""
