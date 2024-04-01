import pickle
from dataclasses import InitVar, dataclass, field
# import graph
from typing import List

import networkx as nx
import numpy as np
from networkx.algorithms.isomorphism import is_isomorphic
from structs.case import Case
from structs.dataset import DataSet
from structs.valency import Valency
import copy


def bond_type_to_str(type):
    if type == 0:
        return "va"
    if type == 1:
        return "vb"
    if type == 2:
        return "vc"
    else:
        return type


@ dataclass
class RLState:
    """The reinforcement learning state representation.

    Attributes:
        case: The object containing all metadata about the current case running.
        bb: The indices of the building block groups used.
        num_bb: The number of building block groups used.
        group_data: The dataset of group information.
        group_count: The count vector of all (first order)
            functional groups used in the current fragment.
            Indexing is "short-form", where indices correspond to the
            building blocks group indices sorted in ascending order.
        valency: The object containing all relevant valence information about
            the current fragment.
        graph: Graph representation of the substructure.

    Properties:
        aromatics: Short-form vector counts of aromatic groups.
        nonaromatics: Short-form vector counts of nonaromatic groups.
        cyclics: Short-form vector counts of cyclic groups.
        noncyclics: Short-form vector counts of noncyclic groups.

        i_G_a: Indices (1-indexed) of the aromatic groups.
        i_G_na: Indices (1-indexed) of the nonaromatic groups.
        i_G_c: Indices (1-indexed) of the cylic groups.
        i_G_nc: Indices (1-indexed) of the noncyclic groups.

        n_G_a: Long-form vector counts of the aromatic groups
        n_G_na: Long-form vector counts of the nonaromatic groups.
        n_G_c: Long-form vector counts of the cyclic groups.
        n_G_nc: Long-form vector counts of the noncyclic groups.
        n_G: Long-form vector count of all groups.

        n_a: Total number of aromatic groups.
        n_na: Total number of nonaromatic groups.
        n_c: Total number of cyclic groups.
        n_nc: Total number of acyclic groups.


        n_i: Total number of group i.
        rings: Total number of rings.

    Methods:
        G_i: Returns the number of groups with valency >= i.


    The key is generated by hashing valency, group information, and spectral
    eigenvalues pertaining to a molecular graph.
    """

    case: Case
    bb: np.ndarray = None
    graph: nx.Graph = nx.Graph()
    group_data: DataSet = field(init=False)
    group_count: np.ndarray = None
    valency: Valency = None
    num_bb: int = field(init=False)

    def __post_init__(self):
        self.max_per_group = 10
        self.laplacian = nx.normalized_laplacian_matrix(
            self.graph, weight='valency') if len(self.graph.nodes()) != 0 else None
        self.num_bb = len(self.case.bb)
        self.group_data = self.case.group_data
        if (self.bb is None):
            self.bb = self.case.bb
        if (self.group_count is None):
            self.group_count = np.zeros((self.num_bb,))
        if (self.valency is None):
            self.valency = Valency(self.graph, self.max_per_group, self.num_bb)
        self.valence_invalid = False
        # self.gnn_model = pickle.load(open(path, 'rb'))
        # self.second_order_queries = self.load_queries()
        # self.second_ord_idxs, self.second_ord_count = self.get_second_order()

    # def __eq__(self, obj):
    #     return self.graph.is_isomorphic(self.graph, obj)

    def is_empty(self):
        return np.sum(self.group_count) == 0

    def nodeadd_params(self, bb_idx, bond_type):
        max_per_group = 10
        group_idx = self.bb[bb_idx] - 1
        G = self.graph.copy()
        total, va, vb, vc = self.group_data.valences
        total, va, vb, vc = total[group_idx], va[group_idx], vb[group_idx], vc[group_idx]
        # print(G.nodes(data=True))

        if self.is_empty():
            tmp = []
            bond_type = None
        else:
            tmp = ([node["inner_idx"] for id, node in G.nodes(
                data=True) if node['group'] == group_idx + 1])

        inner_idx = (max(tmp) + 1) if len(tmp) != 0 else 0

        if (inner_idx >= max_per_group):
            raise Exception("exceeds max allowed count per group")

        return {
            'va_full': va,
            'vb_full': vb,
            'vc_full': vc,
            'va': va - (1 if (bond_type == "va" or bond_type == 0) else 0),
            'vb': vb - (1 if (bond_type == "vb" or bond_type == 1) else 0),
            'vc': vc - (1 if (bond_type == "vc" or bond_type == 2) else 0),
            'group': group_idx + 1,
            'valency': total - (1 if bond_type is not None else 0),
            'idx': bb_idx * max_per_group + inner_idx,
            'inner_idx': inner_idx,
            'bb_idx': bb_idx
        }

    def RLState_params(self, G, gc):
        return {'bb': None,
                'graph': G,
                'group_count': gc,
                'valency': Valency(G, self.max_per_group, self.num_bb)
                }

    def add_group(self, params):
        """Adds a group to the current fragment. bb_idx is 0-indexed.

        Args:

        Returns:

        """
        bb_idx, bond_type_h, tail, bond_type_t, enum = params
        max_per_group = 10
        G = copy.deepcopy(self.graph)
        bond_type_t = bond_type_to_str(bond_type_t)
        params = self.nodeadd_params(bb_idx, bond_type_h)
        t_idx = tail * max_per_group + enum

        if self.is_empty() or self.has_avail_valence(t_idx, G, bond_type_t):
            h_idx = params["bb_idx"] * max_per_group + params["inner_idx"]
            G.add_node(h_idx, **params)
            if not self.is_empty():
                G.add_edge(h_idx, t_idx)
                self.update_tail_valence(G.nodes[t_idx], bond_type_t)

            gc = self.group_count.copy()
            gc[bb_idx] += 1
            params = self.RLState_params(G, gc)
            return RLState(self.case, **params)
        else:
            return None

    def is_empty(self):
        return sum(self.group_count) == 0

    def has_avail_valence(self, tail, G, bond_type):
        return (tail in list(G.nodes) and G.nodes[tail][bond_type] != 0)

    # TODO
    def get_second_order(self):
        """Perform subgraph matching with the second order query graphs
        that subsume the chosen building blocks in the case.

        Returns: all found second order groups.
        """
        anchors = self.graph.nodes

    def load_queries(self):
        return pickle.load(open(path, 'rb'))

    def update_tail_valence(self, tail_node, bond_type):
        # print(tail_node)
        if bond_type == 0:
            bond_type = "va"
        if bond_type == 1:
            bond_type = "vb"
        if bond_type == 2:
            bond_type = "vc"
        if tail_node[bond_type] == 0:
            raise Exception()
        else:
            # print(tail_node)
            tail_node[bond_type] -= 1
            tail_node["valency"] -= 1

    def to_full_vec(self):
        fv = np.zeros((350,))
        fv[self.bb - 1] = self.group_count
        return fv

    def to_full_vec_2(self):
        fv = np.zeros((350,))
        fv[self.bb - 1] = self.group_count
        # fv[self.second_ord_idxs - 1] = self.second_ord_count
        return fv

    def has_available_bonds(self):
        pass

    def __hash__(self):
        return (self.laplacian.toarray().tobytes() if self.laplacian is not None else np.array([0]).tobytes())  \
            + self.valency.tobytes() \
            + self.group_count.tobytes()

    def key(self):
        return (self.laplacian.toarray().tobytes() if self.laplacian is not None else np.array([0]).tobytes()) \
            + self.valency.tobytes() \
            + self.group_count.tobytes()

    def __eq__(self, obj):
        return self.group_count == obj.group_count \
            and self.bb == obj.bb \
            and self.num_bb == obj.num_bb \
            and self.laplacian == obj.laplacian

    @ property
    def aromatics(self):
        aro_idx = self.case.aromatics - 1
        fv = self.to_full_vec()
        return fv[aro_idx]

    @ property
    def nonaromatics(self):
        nonaro_idx = self.case.nonaromatics - 1
        fv = self.to_full_vec()
        return fv[nonaro_idx]

    @ property
    def cyclics(self):
        cyclics_idx = self.case.cyclics - 1
        fv = self.to_full_vec()
        return fv[cyclics_idx]

    @ property
    def noncyclics(self):
        noncyclics_idx = self.case.noncyclics - 1
        fv = self.to_full_vec()
        return fv[noncyclics_idx]

    @ property
    def i_G_a(self):
        mask = np.isin(self.bb, self.case.aromatics)
        A = (np.where(mask, self.bb, 0))
        return A[A != 0]

    @ property
    def i_G_na(self):
        mask = np.isin(self.bb, self.case.nonaromatics)
        A = (np.where(mask, self.bb, 0))
        return A[A != 0]

    @ property
    def i_G_c(self):
        mask = np.isin(self.bb, self.case.cyclics)
        A = (np.where(mask, self.bb, 0))
        return A[A != 0]

    @ property
    def i_G_nc(self):
        mask = np.isin(self.bb, self.case.noncyclics)
        A = (np.where(mask, self.bb, 0))
        return A[A != 0]

    @ property
    def n_G_a(self, v=None):
        return np.sum(self.to_full_vec()[self.i_G_a - 1])

    @ property
    def n_G_na(self, v=None):
        return np.sum(self.to_full_vec()[self.i_G_na - 1])

    @ property
    def n_G_c(self, v=None):
        return self.to_full_vec()[self.i_G_c - 1]

    @ property
    def n_G_nc(self, v=None):
        return np.sum(self.to_full_vec()[self.i_G_nc - 1])

    @ property
    def n_nc(self):
        return np.sum(self.n_G_nc)

    @ property
    def n_c(self):
        return np.sum(self.n_G_c)

    @ property
    def n_a(self):
        return np.sum(self.n_G_a)

    @ property
    def n_na(self):
        return np.sum(self.n_G_na)

    @ property
    def rings(self):
        if (self.numAro % 6 == 0):
            rings = self.numAro // 6

        return rings

    @ property
    def n_G(self):
        return np.sum(self.group_count)

    @ property
    def G_i(self, v):
        gc = self.group_count
        return np.sum(gc[np.where(gc >= v)])

    def is_valid(self):
        # TODO
        return self.valence_invalid

    @property
    def obs(self):
        # print(self.valency.total.flatten().shape)
        return {
            'group_counts': self.group_count,
            'vtotal': self.valency.total.flatten(),
            'va': self.valency.va.flatten(),
            'vb': self.valency.vb.flatten(),
            'vc': self.valency.vc.flatten(),
        }

    @ property
    def n_i(self, i):
        return self.to_full_vec()[i]

    def show(self):
        nx.draw(self.graph)

    def __repr__(self):
        return f"--------State-------\n" + \
            f"{'building blocks': <20}{self.bb}\n" + \
            f"{'group count:': <20}{self.group_count}\n" + \
            f"{'# building blocks:': <20}{self.num_bb}\n" + \
            f"---------------------"
        # TODO

    def to_smiles(self):
        pass

    def to_smarts(self):
        pass
