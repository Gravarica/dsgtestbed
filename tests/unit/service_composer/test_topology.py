import pytest

from dsg.service_composer.topology import TopologyInvalid, topology_of


def test_chain_knows_who_comes_next_and_who_is_first():
    chain = topology_of(["qr", "cv", "pc"], ["qr -> cv", "cv -> pc"])
    assert chain.next_hops_of("qr") == ["cv"]
    assert chain.feeders_of("pc") == ["cv"]
    assert chain.sources() == ["qr"]
    assert chain.from_first_to_last() == ["qr", "cv", "pc"]


def test_order_follows_the_edges_not_the_order_in_the_file():
    assert topology_of(["pc", "cv", "qr"], ["cv -> pc", "qr -> cv"]).from_first_to_last() == ["qr", "cv", "pc"]


def test_one_service_alone_is_a_topology_without_edges():
    alone = topology_of(["qr"], [])
    assert alone.sources() == ["qr"]
    assert alone.next_hops_of("qr") == []


def test_branching_and_merging_are_understood():
    graph = topology_of(["a", "b", "c", "d"], ["a -> b", "a -> c", "b -> d", "c -> d"])
    assert graph.next_hops_of("a") == ["b", "c"]
    assert graph.feeders_of("d") == ["b", "c"]
    assert graph.from_first_to_last()[0] == "a" and graph.from_first_to_last()[-1] == "d"


def test_edges_may_be_written_as_text_or_as_pairs():
    assert topology_of(["a", "b"], [["a", "b"]]).edges == (("a", "b"),)


@pytest.mark.parametrize(
    "nodes, edges, complaint",
    [
        (["qr", "cv"], ["qr -> cv", "cv -> qr"], "cycle"),
        (["qr"], ["qr -> ghost"], "do not exist"),
        (["qr"], ["qr -> qr"], "feeds itself"),
        (["qr", "cv"], ["qr cv"], "written as"),
        (["QR_Detector"], [], "small letters"),
        ([], [], "no nodes"),
    ],
)
def test_topologies_that_cannot_work_are_refused_in_plain_words(nodes, edges, complaint):
    with pytest.raises(TopologyInvalid, match=complaint):
        topology_of(nodes, edges)
